"""Issuing, checking and revoking API tokens (docs/adr/0007)."""

import hashlib
import hmac
import secrets
from collections.abc import Iterable
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from housecairn.accounts.models import User
from housecairn.apitokens.models import ApiToken, Scope
from housecairn.homes import services as home_services
from housecairn.homes.models import Home

TOKEN_PREFIX = "hc_"  # noqa: S105 - public prefix, not a secret
_DEFAULT = object()


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
        raise ValidationError("A token needs at least one scope.")
    home_list = list(homes)
    if not home_list:
        raise ValidationError("A token is bound to at least one home.")
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
    # The lookup compares digests, which reveal nothing about the secret; the
    # constant-time comparison is a second guard, independent of the database.
    if token is None or not hmac.compare_digest(token.digest, digest):
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
