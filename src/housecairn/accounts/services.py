"""Who may create an account by signing in through OIDC (docs/adr/0007).

Sign-up through OIDC is closed by default. A sign-in without a matching
account is refused, except:

- while the instance has never had an account: the first sign-in creates the
  instance administrator (bootstrap), optionally restricted to one verified
  address with `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL`;
- when the operator opens sign-up to everyone the provider accepts
  (`HOUSECAIRN_OIDC_SIGNUP=open`);
- when the address has an invitation (not implemented yet, see
  `has_invitation`).

Accounts created in the last two cases have no administration rights.
"""

import enum
import logging
from collections.abc import Callable

from django.conf import settings
from django.db import IntegrityError, transaction

from housecairn.accounts.models import InstanceSetup, SetupMethod, User

logger = logging.getLogger("housecairn.security")

SIGNUP_CLOSED = "closed"
SIGNUP_OPEN = "open"


class Decision(enum.Enum):
    BOOTSTRAP_ADMIN = "bootstrap_admin"
    MEMBER = "member"
    REFUSED = "refused"


class FirstAccountTakenError(Exception):
    """Another sign-in created the first account in the meantime."""


def instance_has_accounts() -> bool:
    """True once the instance has had an account, even if it was deleted since."""
    return InstanceSetup.objects.exists() or User.objects.exists()


def same_address(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def may_bootstrap(email: str | None, email_verified: bool) -> bool:
    """Whether this identity may become the first administrator."""
    pinned: str = settings.HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL
    if not pinned:
        return True
    return bool(email) and email_verified and same_address(email or "", pinned)


def has_invitation(email: str | None) -> bool:
    """Whether an invitation lets this address sign up through OIDC.

    Extension point for invitations, which come with the account management
    work: return True when an unused, unexpired invitation exists for this
    address. Until then nobody is invited.
    """
    return False


def oidc_signup_decision(email: str | None, email_verified: bool) -> Decision:
    """What a sign-in through OIDC without a matching account leads to."""
    if not instance_has_accounts():
        # Before the first account, only the bootstrap rule applies, even when
        # sign-up is open: nobody else may take the administrator's place.
        return (
            Decision.BOOTSTRAP_ADMIN if may_bootstrap(email, email_verified) else Decision.REFUSED
        )
    if settings.HOUSECAIRN_OIDC_SIGNUP == SIGNUP_OPEN or has_invitation(email):
        return Decision.MEMBER
    return Decision.REFUSED


def create_first_admin(user: User, save: Callable[[], User]) -> User:
    """Save `user` as the instance administrator, if it is still the first account.

    `save` stores the user and its linked identity. Everything runs in one
    transaction that also inserts the single `InstanceSetup` row: of two
    simultaneous first sign-ins, one inserts it and the other fails on the
    primary key (or, with SQLite, waits for the first and then sees its
    account). The loser gets `FirstAccountTakenError` and nothing of it is kept.
    """
    try:
        with transaction.atomic():
            if instance_has_accounts():
                raise FirstAccountTakenError
            setup = InstanceSetup.objects.create(method=SetupMethod.OIDC)
            user.is_staff = True
            user.is_superuser = True
            saved = save()
            setup.first_user = saved
            setup.save(update_fields=["first_user"])
    except IntegrityError as exc:
        raise FirstAccountTakenError from exc
    logger.warning(
        "first account created as instance administrator via OIDC",
        extra={"user_id": str(saved.pk)},
    )
    return saved


def record_first_account(user: User) -> None:
    """Mark the instance as set up when its first account is created otherwise."""
    if InstanceSetup.objects.exists():
        return
    try:
        with transaction.atomic():
            InstanceSetup.objects.create(method=SetupMethod.OTHER, first_user=user)
    except IntegrityError:
        # Another account was first; the instance is set up either way.
        pass
