"""What the administrator of the instance does: invitations, unlocking (docs/adr/0022).

Nothing here reads a home: invitations belong to the instance, and the one
action that touches homes (`unlock_removed_providers`) returns a count.
"""

import secrets
from collections.abc import Callable, Iterable
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from housecairn.accounts.models import User
from housecairn.accounts.services import is_instance_admin
from housecairn.audit import services as audit
from housecairn.homes import services as home_services
from housecairn.instance.models import InstanceInvitation

INSTANCE_PREFIX = "hcn_"


def _require_admin(actor: Any) -> None:
    if not is_instance_admin(actor):
        raise PermissionDenied


def _new_secret() -> tuple[str, str]:
    raw = INSTANCE_PREFIX + secrets.token_urlsafe(32)
    return raw, home_services.hash_invitation(raw)


def _lifetime() -> timedelta:
    return timedelta(days=settings.HOUSECAIRN_INVITATION_LIFETIME_DAYS)


def pending_invitations() -> models.QuerySet[InstanceInvitation]:
    return InstanceInvitation.objects.filter(
        accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now()
    ).order_by("-sent_at")


def invite(
    actor: User, *, email: str, send: Callable[[InstanceInvitation, str], None]
) -> InstanceInvitation:
    """Invite an address to create an account, by email.

    The answer does not depend on whether an account already uses the address:
    an administrator learns nothing about accounts by inviting, and the person
    invited with an account of their own is simply told to sign in when they
    open the link.
    """
    _require_admin(actor)
    address = email.strip()
    with transaction.atomic():
        now = timezone.now()
        InstanceInvitation.objects.filter(
            email__iexact=address,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__lte=now,
        ).update(revoked_at=now)
        if any(home_services.same_address(i.email, address) for i in pending_invitations()):
            raise ValidationError(
                _("An invitation to this address is already pending; send it again instead.")
            )
        raw, digest = _new_secret()
        invitation = InstanceInvitation(
            email=address,
            invited_by=actor,
            digest=digest,
            expires_at=now + _lifetime(),
            sent_at=now,
        )
        invitation.full_clean(exclude=["digest"])
        try:
            with transaction.atomic():
                invitation.save()
        except IntegrityError as exc:
            raise ValidationError(
                _("An invitation to this address is already pending; send it again instead.")
            ) from exc
        audit.record("instance_invitation.sent", actor=actor)
    home_services.deliver(invitation, raw, send)
    return invitation


def resend(
    actor: User, invitation: InstanceInvitation, *, send: Callable[[InstanceInvitation, str], None]
) -> InstanceInvitation:
    """A new link and a new expiry; the previous link stops working."""
    _require_admin(actor)
    if invitation.accepted_at is not None or invitation.revoked_at is not None:
        raise ValidationError(_("This invitation was already accepted or revoked."))
    raw, digest = _new_secret()
    now = timezone.now()
    with transaction.atomic():
        invitation.digest = digest
        invitation.sent_at = now
        invitation.expires_at = now + _lifetime()
        invitation.save(update_fields=["digest", "sent_at", "expires_at", "updated_at"])
        audit.record("instance_invitation.resent", actor=actor)
    home_services.deliver(invitation, raw, send)
    return invitation


def revoke(actor: User, invitation: InstanceInvitation) -> None:
    _require_admin(actor)
    if invitation.revoked_at is None and invitation.accepted_at is None:
        with transaction.atomic():
            invitation.revoked_at = timezone.now()
            invitation.save(update_fields=["revoked_at", "updated_at"])
            audit.record("instance_invitation.revoked", actor=actor)


def find(raw: str) -> InstanceInvitation | None:
    """The pending invitation matching this link secret; dead links all give None."""
    if not isinstance(raw, str) or not raw.startswith(INSTANCE_PREFIX) or len(raw) > 200:
        return None
    invitation: InstanceInvitation | None = InstanceInvitation.objects.filter(
        digest=home_services.hash_invitation(raw)
    ).first()
    if invitation is None or not invitation.is_pending:
        return None
    return invitation


def has_pending(email: str) -> bool:
    """Whether the instance has a pending invitation for this address."""
    return any(
        home_services.same_address(i.email, email)
        for i in InstanceInvitation.objects.filter(
            email__iexact=email.strip(),
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
    )


@transaction.atomic
def accept(user: User, raw: str) -> InstanceInvitation:
    """Use the invitation up for the account that opened its link.

    The account's address must be the invited one; the link reached that
    mailbox, which verifies the address.
    """
    found = find(raw)
    if found is None:
        raise InstanceInvitation.DoesNotExist
    invitation: InstanceInvitation = InstanceInvitation.objects.select_for_update().get(pk=found.pk)
    if not invitation.is_pending:
        raise InstanceInvitation.DoesNotExist
    if not home_services.same_address(user.email, invitation.email):
        raise PermissionDenied(_("This invitation is for another email address."))
    home_services.verify_address(user, invitation.email)
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["accepted_at", "accepted_by", "updated_at"])
    audit.record("instance_invitation.accepted", actor=user)
    return invitation


@transaction.atomic
def create_account(raw: str, *, password: str) -> User:
    """Create the account of an invited address, then use the invitation up."""
    invitation = find(raw)
    if invitation is None:
        raise InstanceInvitation.DoesNotExist
    if User.objects.filter(email__iexact=invitation.email).exists():
        raise ValidationError(_("An account already uses this address: sign in."))
    user = User.objects.create_user(email=invitation.email, password=password)
    audit.record("account.created", actor=user, by="instance_invitation")
    accept(user, raw)
    return user


def accept_for_identity(user: User) -> None:
    """An account created through the provider for an invited, verified address."""
    for invitation in pending_invitations().filter(email__iexact=user.email):
        invitation.accepted_at = timezone.now()
        invitation.accepted_by = user
        invitation.save(update_fields=["accepted_at", "accepted_by", "updated_at"])
        audit.record("instance_invitation.accepted", actor=user)


def unlock_removed_providers(actor: User, *, declared: Iterable[str]) -> int:
    """Clear the sign-in rule of every home that points to a provider that is gone.

    The administrator cannot open homes, so this is the way out for them: it
    frees homes without naming or reading any, and reports how many.
    """
    _require_admin(actor)
    with transaction.atomic():
        count = home_services.lift_all_unavailable_requirements(declared=declared)
        if count:
            audit.record("homes.unlocked", actor=actor, count=count)
    return count
