"""The display name a sign-in provider gives (docs/adr/0045).

At each sign-in through an OpenID Connect provider, the display name is read from the
claims of the identity (userinfo, then the ID token), in this order: `name`, then
`given_name` and `family_name` together, then `preferred_username`, then `nickname`. The
first one that is a valid display name for `services.clean_display_name` is taken; the
others are ignored, with one log line per reason and never the value. When none is valid
the name stays as it was (or absent): a provider's claim never makes a sign-in fail.

The name is written only while the person has not typed one (`display_name_source` is
`oidc`). Nothing else of the identity is kept: no claim, no address, no picture. allauth
keeps the claims of the last sign-in of each linked identity in `SocialAccount.extra_data`,
as it did before; that is what **Use the provider's name** reads to apply at once.
"""

import logging
from collections.abc import Iterator
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from housecairn.accounts import names, services
from housecairn.accounts.models import DisplayNameSource, User

logger = logging.getLogger("housecairn.security")

# The claims read, in order of preference; a tuple is joined with a space.
CLAIMS: tuple[tuple[str, ...], ...] = (
    ("name",),
    ("given_name", "family_name"),
    ("preferred_username",),
    ("nickname",),
)


def claims_of(extra_data: Any) -> dict[str, Any]:
    """The claims of an identity as allauth stores them: userinfo over the ID token."""
    data = extra_data if isinstance(extra_data, dict) else {}
    merged: dict[str, Any] = {}
    nested = False
    for part in ("id_token", "userinfo"):
        if isinstance(data.get(part), dict):
            merged.update(data[part])
            nested = True
    # allauth before 65.11 stored the userinfo response itself.
    return merged if nested else dict(data)


def _candidates(claims: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    for keys in CLAIMS:
        present = [claims[key] for key in keys if key in claims and claims[key] is not None]
        if not present:
            continue
        label = "+".join(keys)
        if not all(isinstance(value, str) for value in present):
            yield label, None
        else:
            yield label, " ".join(present)


def _reason(value: Any) -> str:
    """Why a claim cannot be a display name, in a word for the log; empty if it can."""
    if not isinstance(value, str):
        return "not text"
    if len(value) > 4 * names.DISPLAY_NAME_MAX_LENGTH:
        return "too long"
    if names.looks_like_an_address(value):
        return "contains @"
    # Markup is no name: a provider whose attribute holds HTML is misconfigured. A person
    # may still type these characters (they are escaped on every page).
    if "<" in value or ">" in value:
        return "markup"
    try:
        cleaned = services.clean_display_name(value)
    except ValidationError:
        # Over 60 characters once cleaned, or nothing that draws.
        return "too long" if names.has_visible_glyph(value) else "nothing visible"
    return "" if cleaned else "empty"


def name_from_claims(claims: dict[str, Any]) -> str | None:
    """The display name the claims give, cleaned; None when none of them can be one."""
    refused: dict[str, list[str]] = {}
    found = None
    for label, value in _candidates(claims):
        reason = _reason(value)
        if not reason:
            found = services.clean_display_name(value)
            break
        refused.setdefault(reason, []).append(label)
    for reason, labels in refused.items():
        # The claim names, never their values: they are the person's identity.
        logger.info(
            "Display name from the sign-in provider ignored (%s): %s", reason, ", ".join(labels)
        )
    return found


def apply(user: User, extra_data: Any, provider: str) -> bool:
    """Take the display name from a sign-in through `provider`; whether it changed.

    Only while the source is `oidc`: a name the person typed stays.
    """
    if user.display_name_source != DisplayNameSource.OIDC:
        return False
    name = name_from_claims(claims_of(extra_data))
    if name is None:
        return False
    if name == user.display_name and provider == user.display_name_provider:
        return False
    user.display_name = name
    user.display_name_provider = provider[:32]
    user.save(update_fields=["display_name", "display_name_provider", "updated_at"])
    return True


def on_sign_in(user: Any, sociallogin: Any) -> None:
    """After a sign-in through a provider: the provider used gives the name."""
    if not isinstance(user, User) or user.pk is None:
        return
    account = getattr(sociallogin, "account", None)
    provider = str(getattr(account, "provider", "") or "")
    if not provider:
        return
    apply(user, getattr(account, "extra_data", None), provider)


def use_provider_name(user: User) -> bool:
    """Give the display name back to the sign-in provider; whether it is in effect now.

    The source becomes `oidc`. The name is taken right away from the claims allauth kept of
    the identity used last; otherwise it is taken at the next sign-in through a provider.
    """
    from allauth.socialaccount.models import SocialAccount

    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if locked.display_name_source != DisplayNameSource.OIDC:
            locked.display_name_source = DisplayNameSource.OIDC
            locked.display_name_provider = ""
            locked.save(
                update_fields=["display_name_source", "display_name_provider", "updated_at"]
            )
        last = SocialAccount.objects.filter(user=locked).order_by("-last_login").first()
        if last is not None:
            apply(locked, last.extra_data, last.provider)
    user.refresh_from_db()
    return bool(user.display_name_provider)


def keep_typed_name(user: User) -> None:
    """Keep the current display name as the person's own: no provider changes it."""
    if user.display_name_source != DisplayNameSource.MANUAL:
        user.display_name_source = DisplayNameSource.MANUAL
        user.display_name_provider = ""
        user.save(update_fields=["display_name_source", "display_name_provider", "updated_at"])


def has_provider(user: Any) -> bool:
    """Whether the account is linked to at least one sign-in provider."""
    from allauth.socialaccount.models import SocialAccount

    return bool(getattr(user, "pk", None)) and SocialAccount.objects.filter(user=user).exists()
