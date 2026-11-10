"""The first administrator, created on a web screen with a one-time code (docs/adr/0055).

While the instance has no active administrator, a code is written in the process log
at start-up (`manage.py setup_code`, run by the container's entry point). Whoever reads
the log can open `/setup/`, give the code, and create the first administrator. The
code is random (160 bits), stored as a digest, valid for `CODE_LIFETIME`, and used up
by the first account it creates. Once an administrator exists, no code is issued or
accepted and the screen answers 404; `HOUSECAIRN_SETUP_SCREEN=false` turns it off.

OIDC bootstrap (`services.create_first_admin`) and `createsuperuser` stay as they were:
whichever creates the first administrator first closes the other two.
"""

import base64
import hashlib
import hmac
import logging
import re
import secrets
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from housecairn.accounts.models import InstanceSetup, SetupCode, SetupMethod, User

logger = logging.getLogger("housecairn.security")

# Long enough to read the log after a deployment and fill in the form; short enough that a
# code left in a log archive is useless soon after. Each start issues a new one.
CODE_LIFETIME = timedelta(hours=1)
CODE_BYTES = 20  # 160 bits
GROUP = 4


class SetupCodeInvalidError(Exception):
    """The code is wrong, expired or already used; the three cases are not told apart."""


class SetupClosedError(Exception):
    """An administrator exists meanwhile (or the screen is off): nothing to set up."""


def screen_enabled() -> bool:
    return bool(settings.HOUSECAIRN_SETUP_SCREEN)


def admin_exists() -> bool:
    return User.objects.filter(is_active=True, is_staff=True, is_superuser=True).exists()


def is_available() -> bool:
    """Whether the first-account screen exists: on, and no administrator yet."""
    return screen_enabled() and not admin_exists()


def normalize(code: str) -> str:
    """The code as compared: no space or hyphen, upper case."""
    return re.sub(r"[\s-]", "", code or "").upper()


def digest_of(code: str) -> str:
    # A fast hash is enough: the code has 160 bits of entropy, unlike a password.
    return hashlib.sha256(normalize(code).encode("utf-8")).hexdigest()


def present(raw: str) -> str:
    """The code in groups of four, to read and type: ABCD-EFGH-..."""
    return "-".join(raw[i : i + GROUP] for i in range(0, len(raw), GROUP))


def issue_code() -> str | None:
    """A new code, replacing the unused ones; None when no screen should exist.

    Also forgets every code once an administrator exists.
    """
    with transaction.atomic():
        if not is_available():
            SetupCode.objects.filter(used_at__isnull=True).delete()
            return None
        SetupCode.objects.filter(used_at__isnull=True).delete()
        raw = base64.b32encode(secrets.token_bytes(CODE_BYTES)).decode("ascii")
        SetupCode.objects.create(digest=digest_of(raw), expires_at=timezone.now() + CODE_LIFETIME)
    return present(raw)


def _find_usable(code: str) -> SetupCode | None:
    """The unused, unexpired code that matches, compared in constant time.

    Every candidate is compared, none is skipped on a match, so the time taken does not
    say how much of the code was right.
    """
    wanted = digest_of(code)
    found: SetupCode | None = None
    for candidate in SetupCode.objects.filter(used_at__isnull=True, expires_at__gt=timezone.now()):
        if hmac.compare_digest(candidate.digest, wanted):
            found = candidate
    return found


def create_first_admin(*, code: str, email: str, name: str, password: str) -> User:
    """Create the first administrator if `code` is good, use the code up, and audit it.

    Everything happens in one transaction: the code is claimed by a conditional UPDATE
    (of two simultaneous submissions only one changes a row, on every database), and any
    later failure gives the code back. Raises `SetupCodeInvalidError` for a code that is
    not usable, `SetupClosedError` when there is nothing to set up any more, and
    `ValidationError` when the address is taken.
    """
    from housecairn.audit import services as audit

    if not is_available():
        raise SetupClosedError
    address = User.objects.normalize_email(email.strip())
    try:
        with transaction.atomic():
            candidate = _find_usable(code)
            if candidate is None:
                raise SetupCodeInvalidError
            claimed = SetupCode.objects.filter(
                pk=candidate.pk, used_at__isnull=True, expires_at__gt=timezone.now()
            ).update(used_at=timezone.now())
            if not claimed:
                raise SetupCodeInvalidError
            if admin_exists():
                raise SetupClosedError
            if User.objects.filter(email__iexact=address).exists():
                raise ValidationError(_("An account already uses this address."))
            setup: InstanceSetup | None = None
            if not InstanceSetup.objects.exists() and not User.objects.exists():
                # The row an OIDC sign-in would insert too: of the two, one fails on the key.
                setup = InstanceSetup.objects.create(method=SetupMethod.SETUP_SCREEN)
            user = User.objects.create_superuser(
                email=address, password=password, display_name=name
            )
            EmailAddress.objects.create(user=user, email=address, primary=True, verified=True)
            if setup is not None:
                setup.first_user = user
                setup.save(update_fields=["first_user"])
            audit.record("instance.first_admin_created", actor=user, by="setup_screen")
    except IntegrityError as exc:
        # The row of `InstanceSetup` or the address was taken by a simultaneous request.
        if admin_exists():
            raise SetupClosedError from exc
        raise ValidationError(_("An account already uses this address.")) from exc
    logger.warning(
        "first account created as instance administrator via the setup screen",
        extra={"user_id": str(user.pk)},
    )
    return user
