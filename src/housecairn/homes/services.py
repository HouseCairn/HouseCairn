"""Business rules about homes, households and invitations (docs/adr/0002, 0006, 0020, 0021).

Web views and API views call these functions; neither holds rules of its own.
"""

import hashlib
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from housecairn.accounts.models import User
from housecairn.homes.models import WRITE_ROLES, Home, Invitation, Membership, Role

AnyUser = User | AnonymousUser

INVITATION_PREFIX = "hci_"


class SsoRequiredError(Exception):
    """The home requires a sign-in through a provider this session did not use."""

    def __init__(self, home: Home) -> None:
        super().__init__(home.required_provider)
        self.home = home
        self.provider_id = home.required_provider


def homes_for(user: AnyUser, *, restrict_to: Iterable[UUID] | None = None) -> models.QuerySet[Home]:
    """Homes the user belongs to; optionally only those in `restrict_to`.

    This is the single entry point that limits every query to the user's homes.
    """
    if not user.is_authenticated or not user.is_active:
        return Home.objects.none()
    member_of = Membership.objects.filter(user=user).values("home_id")
    homes = Home.objects.filter(id__in=member_of)
    if restrict_to is not None:
        homes = homes.filter(id__in=list(restrict_to))
    return homes


def open_homes(homes: models.QuerySet[Home], providers: frozenset[str]) -> models.QuerySet[Home]:
    """Of `homes`, those whose sign-in requirement `providers` satisfies (docs/adr/0021)."""
    return homes.filter(models.Q(required_provider="") | models.Q(required_provider__in=providers))


def is_open(home: Home, providers: frozenset[str]) -> bool:
    return not home.required_provider or home.required_provider in providers


def check_open(home: Home, providers: frozenset[str]) -> None:
    if not is_open(home, providers):
        raise SsoRequiredError(home)


def role_of(user: AnyUser, home: Home) -> Role | None:
    if not user.is_authenticated:
        return None
    membership = Membership.objects.filter(user=user, home=home).first()
    return Role(membership.role) if membership else None


def can_write(user: AnyUser, home: Home) -> bool:
    return role_of(user, home) in WRITE_ROLES


def is_owner(user: AnyUser, home: Home) -> bool:
    return role_of(user, home) == Role.OWNER


def _require_owner(user: AnyUser, home: Home) -> None:
    if not is_owner(user, home):
        raise PermissionDenied


@transaction.atomic
def create_home(owner: User, *, name: str, currency: str = "EUR") -> Home:
    home = Home(name=name, currency=currency)
    home.full_clean()
    home.save()
    Membership.objects.create(home=home, user=owner, role=Role.OWNER)
    return home


def update_home(actor: AnyUser, home: Home, **changes: Any) -> Home:
    if not can_write(actor, home):
        raise PermissionDenied
    allowed = {"name", "currency"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Cannot change: {', '.join(sorted(unknown))}")
    for field, value in changes.items():
        setattr(home, field, value)
    home.full_clean()
    home.save(update_fields=[*changes, "updated_at"])
    return home


def set_required_provider(
    actor: AnyUser,
    home: Home,
    provider_id: str,
    *,
    declared: Iterable[str],
    signed_in_with: frozenset[str],
) -> Home:
    """Require (or, with "", stop requiring) a sign-in provider for this home.

    Only an owner may, only for a provider the instance declares, and only from
    a session signed in through that provider: an owner cannot lock the home
    against the session that sets the rule, nor name a provider nobody can use.
    """
    _require_owner(actor, home)
    if provider_id:
        if provider_id not in set(declared):
            raise ValidationError(_("This sign-in provider is not offered by this instance."))
        if provider_id not in signed_in_with:
            raise ValidationError(
                _("Sign in through this provider first, then require it for the home.")
            )
    home.required_provider = provider_id
    home.save(update_fields=["required_provider", "updated_at"])
    return home


# ---------- household ----------


def members(home: Home) -> models.QuerySet[Membership]:
    """Active members of the home, owners first."""
    order = models.Case(
        models.When(role=Role.OWNER, then=0),
        models.When(role=Role.MEMBER, then=1),
        default=2,
    )
    return (
        Membership.objects.filter(home=home).select_related("user").order_by(order, "user__email")
    )


def _lock_memberships(home: Home) -> list[Membership]:
    """Lock the home's memberships for the rest of the transaction."""
    return list(Membership.objects.select_for_update().filter(home=home))


def _check_an_owner_remains(memberships: list[Membership]) -> None:
    if not any(m.role == Role.OWNER for m in memberships):
        raise ValidationError(_("A home always keeps at least one owner."))


@transaction.atomic
def change_role(actor: AnyUser, membership: Membership, role: Role | str) -> Membership:
    """An owner changes the role of a member, themselves included."""
    new_role = Role(role)
    home = membership.home
    _require_owner(actor, home)
    locked = _lock_memberships(home)
    target = next((m for m in locked if m.pk == membership.pk), None)
    if target is None:
        raise Membership.DoesNotExist
    target.role = new_role
    _check_an_owner_remains(locked)
    target.save(update_fields=["role", "updated_at"])
    return target


@transaction.atomic
def remove_member(actor: AnyUser, membership: Membership) -> None:
    """An owner removes a member; anyone may remove themselves (leaving)."""
    home = membership.home
    if membership.user_id != getattr(actor, "pk", None):
        _require_owner(actor, home)
    locked = _lock_memberships(home)
    target = next((m for m in locked if m.pk == membership.pk), None)
    if target is None:
        raise Membership.DoesNotExist
    _check_an_owner_remains([m for m in locked if m.pk != target.pk])
    target.soft_delete()


def leave_home(actor: User, home: Home) -> None:
    membership = Membership.objects.filter(home=home, user=actor).first()
    if membership is None:
        raise Membership.DoesNotExist
    remove_member(actor, membership)


@transaction.atomic
def transfer_ownership(actor: User, home: Home, to: Membership) -> Membership:
    """The acting owner makes another member owner and becomes a member."""
    _require_owner(actor, home)
    locked = _lock_memberships(home)
    target = next((m for m in locked if m.pk == to.pk), None)
    mine = next((m for m in locked if m.user_id == actor.pk), None)
    if target is None or mine is None:
        raise Membership.DoesNotExist
    if target.pk == mine.pk:
        raise ValidationError(_("Choose another member of the home."))
    target.role = Role.OWNER
    mine.role = Role.MEMBER
    target.save(update_fields=["role", "updated_at"])
    mine.save(update_fields=["role", "updated_at"])
    return target


# ---------- invitations ----------


def hash_invitation(raw: str) -> str:
    """SHA-256, as for API tokens: the secret has 256 bits of entropy."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_secret() -> tuple[str, str]:
    raw = INVITATION_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_invitation(raw)


def _lifetime() -> timedelta:
    return timedelta(days=settings.HOUSECAIRN_INVITATION_LIFETIME_DAYS)


def pending_invitations(home: Home) -> models.QuerySet[Invitation]:
    return Invitation.objects.filter(
        home=home, accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now()
    ).order_by("-sent_at")


def same_address(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


@dataclass(frozen=True)
class Delivery:
    """How an invitation reaches its recipient.

    `send(invitation, raw)` sends the link by email; without it the link is
    returned once to the person who invites, to pass on themselves.
    """

    send: Callable[[Invitation, str], None] | None = None


@transaction.atomic
def invite(
    actor: User, home: Home, *, email: str, role: Role | str, delivery: Delivery
) -> tuple[Invitation, str | None]:
    """Invite an address to the home with a role.

    Returns the invitation and, when it was not sent by email, its link secret
    (shown once). The answer does not depend on whether an account uses the
    address, so inviting cannot be used to find out who has an account.
    """
    _require_owner(actor, home)
    address = email.strip()
    new_role = Role(role)
    if any(same_address(m.user.email, address) for m in members(home)):
        raise ValidationError(_("This person is already a member of the home."))
    if any(same_address(i.email, address) for i in pending_invitations(home)):
        raise ValidationError(
            _("An invitation to this address is already pending; send it again instead.")
        )
    raw, digest = _new_secret()
    now = timezone.now()
    invitation = Invitation(
        home=home,
        email=address,
        role=new_role,
        invited_by=actor,
        digest=digest,
        expires_at=now + _lifetime(),
        sent_at=now,
        delivered_by_email=delivery.send is not None,
    )
    invitation.full_clean(exclude=["digest"])
    invitation.save()
    if delivery.send is not None:
        delivery.send(invitation, raw)
        return invitation, None
    return invitation, raw


@transaction.atomic
def resend_invitation(
    actor: User, invitation: Invitation, *, delivery: Delivery
) -> tuple[Invitation, str | None]:
    """A new link and a new expiry; the previous link stops working."""
    _require_owner(actor, invitation.home)
    if invitation.accepted_at is not None or invitation.revoked_at is not None:
        raise ValidationError(_("This invitation was already accepted or revoked."))
    raw, digest = _new_secret()
    now = timezone.now()
    invitation.digest = digest
    invitation.sent_at = now
    invitation.expires_at = now + _lifetime()
    invitation.delivered_by_email = delivery.send is not None
    invitation.save(
        update_fields=["digest", "sent_at", "expires_at", "delivered_by_email", "updated_at"]
    )
    if delivery.send is not None:
        delivery.send(invitation, raw)
        return invitation, None
    return invitation, raw


def revoke_invitation(actor: User, invitation: Invitation) -> None:
    _require_owner(actor, invitation.home)
    if invitation.revoked_at is None and invitation.accepted_at is None:
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["revoked_at", "updated_at"])


def find_invitation(raw: str) -> Invitation | None:
    """The pending invitation matching this link secret, or None.

    Unknown, accepted, revoked and expired links give the same None: whoever
    holds a dead link learns nothing more from it.
    """
    if not isinstance(raw, str) or not raw.startswith(INVITATION_PREFIX) or len(raw) > 200:
        return None
    invitation: Invitation | None = (
        Invitation.objects.select_related("home").filter(digest=hash_invitation(raw)).first()
    )
    if invitation is None or not invitation.is_pending or invitation.home.deleted_at is not None:
        return None
    return invitation


def has_pending_invitation(email: str) -> bool:
    """Whether some home has a pending invitation for this address."""
    return any(
        same_address(i.email, email)
        for i in Invitation.objects.filter(
            email__iexact=email.strip(),
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
    )


@transaction.atomic
def accept_invitation(user: User, raw: str) -> Membership:
    """Join the home of the invitation, which is then used up.

    The account's address must be the invited one: a forwarded or stolen link
    is of no use to another account. Someone already a member keeps their role.
    """
    invitation = find_invitation(raw)
    if invitation is None:
        raise Invitation.DoesNotExist
    # Lock the row: of two simultaneous acceptances, only one uses it.
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if not invitation.is_pending:
        raise Invitation.DoesNotExist
    if not same_address(user.email, invitation.email):
        raise PermissionDenied(_("This invitation is for another email address."))
    membership: Membership | None = Membership.objects.filter(
        home=invitation.home, user=user
    ).first()
    if membership is None:
        membership = Membership.objects.create(
            home=invitation.home, user=user, role=invitation.role
        )
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["accepted_at", "accepted_by", "updated_at"])
    return membership


@transaction.atomic
def create_account_for_invitation(raw: str, *, password: str) -> User:
    """Create the account of an invited address, then accept the invitation.

    The invitation is the way in when sign-up is closed. The address is marked
    verified only when the link reached it by email.
    """
    from allauth.account.models import EmailAddress

    invitation = find_invitation(raw)
    if invitation is None:
        raise Invitation.DoesNotExist
    if User.objects.filter(email__iexact=invitation.email).exists():
        raise ValidationError(_("An account already uses this address: sign in to accept."))
    user = User.objects.create_user(email=invitation.email, password=password)
    EmailAddress.objects.create(
        user=user, email=user.email, primary=True, verified=invitation.delivered_by_email
    )
    accept_invitation(user, raw)
    return user
