"""Issuing, checking and revoking API tokens (docs/adr/0007)."""

import hashlib
import secrets
from collections.abc import Iterable
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _

from housecairn.accounts.models import User
from housecairn.apitokens.models import ApiToken, Scope
from housecairn.audit import services as audit
from housecairn.core.text import without_control_characters
from housecairn.homes import services as home_services
from housecairn.homes.models import Home

TOKEN_PREFIX = "hc_"  # noqa: S105 - public prefix, not a secret
_DEFAULT = object()

# The lifetimes a person may choose, in days. There is no "never": a token that is
# forgotten is a standing key, and renewing one takes a minute. 90 days is the default of
# the instance (HOUSECAIRN_API_TOKEN_DEFAULT_LIFETIME_DAYS); a year is for an integration
# that is not worth renewing every quarter.
LIFETIME_CHOICES: tuple[int, ...] = (30, 90, 365)
FALLBACK_LIFETIME_DAYS = 90


def _logged_name(token_name: str) -> str:
    """The name of a token as the audit log keeps it: one line, no control characters."""
    return without_control_characters(" ".join(token_name.split()))[: audit.TITLE_MAX_LENGTH]


def default_lifetime_days() -> int:
    """The lifetime offered first: the instance default when it is one of the choices."""
    wanted = settings.HOUSECAIRN_API_TOKEN_DEFAULT_LIFETIME_DAYS
    return wanted if wanted in LIFETIME_CHOICES else FALLBACK_LIFETIME_DAYS


def hash_token(raw: str) -> str:
    """SHA-256 is enough: the secret has 256 bits of entropy, not a password's."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@transaction.atomic
def issue_token(
    user: User,
    *,
    name: str,
    scopes: Iterable[Scope | str],
    homes: Iterable[Home],
    lifetime: timedelta | object | None = _DEFAULT,
) -> tuple[ApiToken, str]:
    """Create a token and return it with its secret, which is shown only once.

    `lifetime=None` makes a token that never expires; the default is
    HOUSECAIRN_API_TOKEN_DEFAULT_LIFETIME_DAYS.
    """
    scope_values = sorted({Scope(s).value for s in scopes})
    if not scope_values:
        raise ValidationError(_("A token needs at least one scope."))
    home_list = list(homes)
    if not home_list:
        raise ValidationError(_("A token is bound to at least one home."))
    visible = set(home_services.homes_for(user).values_list("id", flat=True))
    if any(home.id not in visible for home in home_list):
        raise PermissionDenied
    if lifetime is _DEFAULT:
        lifetime = timedelta(days=settings.HOUSECAIRN_API_TOKEN_DEFAULT_LIFETIME_DAYS)
    expires_at = timezone.now() + lifetime if isinstance(lifetime, timedelta) else None

    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ApiToken.objects.create(
        user=user,
        name=name,
        prefix=raw[: len(TOKEN_PREFIX) + 6],
        digest=hash_token(raw),
        scopes=scope_values,
        expires_at=expires_at,
    )
    token.homes.set(home_list)
    return token, raw


def authenticate(raw: str) -> ApiToken | None:
    """The active token matching this secret, or None."""
    if not raw.startswith(TOKEN_PREFIX):
        return None
    digest = hash_token(raw)
    token: ApiToken | None = ApiToken.objects.select_related("user").filter(digest=digest).first()
    # The lookup is by digest: a timing difference could reveal at most part of
    # a SHA-256 digest, which says nothing about a 256-bit secret.
    if token is None:
        return None
    if not token.is_active or not token.user.is_active:
        return None
    now = timezone.now()
    if token.last_used_at is None or now - token.last_used_at > timedelta(minutes=1):
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
    return token


def revoke_token(actor: User, token: ApiToken) -> None:
    """Revoke a token; its owner or a staff member may do so."""
    if token.user_id != actor.pk and not actor.is_staff:
        raise PermissionDenied
    if token.revoked_at is None:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at", "updated_at"])
        audit.record(
            "apitoken.revoked",
            actor=actor,
            target=None if token.user_id == actor.pk else token.user,
            title=_logged_name(token.name),
        )


# ---------- what a person manages from the screen and the API ----------


def tokens_of(user: User) -> QuerySet[ApiToken]:
    """The tokens of a person that have not been revoked, newest first.

    An expired token is kept in the list, marked as such, so that it can be revoked and
    seen to be the reason an integration stopped.
    """
    return (
        ApiToken.objects.filter(user=user, revoked_at__isnull=True)
        .prefetch_related("homes")
        .order_by("-created_at")
    )


def issuable_homes(user: User) -> QuerySet[Home]:
    """The homes a token may be bound to: the person's, minus those that require a provider.

    A token is not a sign-in through a provider, so it never opens a home that requires
    one (`homes.sso.signed_in_providers`): binding it to such a home would give a token
    that opens nothing.
    """
    return home_services.open_homes(home_services.homes_for(user), frozenset()).order_by("name")


def create_token(
    user: User,
    *,
    name: str,
    scopes: Iterable[Scope | str],
    homes: Iterable[Home],
    lifetime_days: int,
) -> tuple[ApiToken, str]:
    """Issue a token for a person from the screen or the API, and note it in the audit log.

    The log keeps the name the person gave, never the secret.
    """
    if lifetime_days not in LIFETIME_CHOICES:
        raise ValidationError(_("Choose one of the lifetimes offered."))
    allowed = {home.id for home in issuable_homes(user)}
    home_list = list(homes)
    if any(home.id not in allowed for home in home_list):
        raise ValidationError(_("Choose one of your homes."))
    with transaction.atomic():
        token, raw = issue_token(
            user,
            name=name,
            scopes=scopes,
            homes=home_list,
            lifetime=timedelta(days=lifetime_days),
        )
        audit.record("apitoken.created", actor=user, title=_logged_name(name))
    return token, raw
