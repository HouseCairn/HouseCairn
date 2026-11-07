"""Who may create an account by signing in through OIDC (docs/adr/0007).

Sign-up through OIDC is closed by default. A sign-in without a matching
account is refused, except:

- while the instance has never had an account: the first sign-in creates the
  instance administrator (bootstrap), optionally restricted to one verified
  address with `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL`;
- when the operator opens sign-up to everyone the provider accepts
  (`HOUSECAIRN_OIDC_SIGNUP=open`);
- when a home has a pending invitation for the address, and the provider
  says the address is verified (`has_invitation`, docs/adr/0020).

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


# Backends that do not deliver anywhere: the console one prints, the dummy one drops.
_NON_DELIVERING_BACKENDS = frozenset(
    {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
    }
)


def email_is_configured() -> bool:
    """True when the instance can really send email.

    That takes an outgoing server (`EMAIL_HOST`) and a backend that delivers:
    the console backend, the default without `EMAIL_HOST`, only prints. Password
    reset by email is offered only then.
    """
    return bool(settings.EMAIL_HOST) and settings.EMAIL_BACKEND not in _NON_DELIVERING_BACKENDS


def same_address(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def may_bootstrap(email: str | None, email_verified: bool) -> bool:
    """Whether this identity may become the first administrator."""
    pinned: str = settings.HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL
    if not pinned:
        return True
    return bool(email) and email_verified and same_address(email or "", pinned)


def has_invitation(email: str | None, email_verified: bool) -> bool:
    """Whether an invitation lets this identity sign up through OIDC.

    Only for an address the provider asserts as verified: otherwise anyone the
    provider accepts could claim the invited address.
    """
    if not email or not email_verified:
        return False
    from housecairn.homes.services import has_pending_invitation

    return has_pending_invitation(email)


def oidc_signup_decision(email: str | None, email_verified: bool) -> Decision:
    """What a sign-in through OIDC without a matching account leads to."""
    if not instance_has_accounts():
        # Before the first account, only the bootstrap rule applies, even when
        # sign-up is open: nobody else may take the administrator's place.
        return (
            Decision.BOOTSTRAP_ADMIN if may_bootstrap(email, email_verified) else Decision.REFUSED
        )
    if settings.HOUSECAIRN_OIDC_SIGNUP == SIGNUP_OPEN or has_invitation(email, email_verified):
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
