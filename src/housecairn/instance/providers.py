"""Single sign-on providers declared by the administrator in the interface (docs/adr/0041).

A provider set by the `OIDC_*` variables stays as it is and cannot be changed here (the
pairing rule of docs/adr/0035). The others live in `OidcProvider` and are handed to
django-allauth by `accounts.adapters.SocialAccountAdapter.list_apps`, read at each use:
a change applies at once, in every process.

Rules that keep accounts and homes safe:

- the identifier never changes and is never reused, even after deletion;
- the issuer cannot change while identities are linked to the provider: a new issuer
  could assert the same subject as one of them and sign in as its account;
- the client secret does not follow the provider to another issuer: a change of issuer
  clears it unless it is typed again in the same request (the new issuer would otherwise
  receive it at sign-in), and an enabled provider is not left without it;
- a provider that a home requires cannot be deleted (disable it: the homes then follow the
  way out of docs/adr/0021);
- the administrator who acts keeps a way to sign in: a usable password, a passkey, or an
  identity linked to a provider that stays enabled. Disabling or deleting a provider, and
  changing the issuer, client identifier or secret of an enabled one, are refused otherwise.
"""

import http.client
import ipaddress
import json
import logging
import re
import socket
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from housecairn.accounts.models import User
from housecairn.accounts.services import is_instance_admin
from housecairn.audit import services as audit
from housecairn.instance import crypto
from housecairn.instance.models import OidcProvider

logger = logging.getLogger("housecairn.settings")

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
# The variables that declare a provider; shown on the screen, never changed there.
ENVIRONMENT_VARIABLES = (
    "OIDC_SERVER_URL",
    "OIDC_PROVIDER_ID",
    "OIDC_PROVIDER_NAME",
    "OIDC_CLIENT_ID",
)
EDITABLE = ("name", "issuer", "client_id", "pkce", "enabled")
DISCOVERY_PATH = "/.well-known/openid-configuration"
DISCOVERY_MAX_BYTES = 64 * 1024
DISCOVERY_TIMEOUT = 5.0


def _require_admin(actor: Any) -> None:
    if not is_instance_admin(actor):
        raise PermissionDenied


# ---------- what is declared ----------


@dataclass(frozen=True)
class Declared:
    """What the screen and the API say about one provider; never its secret."""

    slug: str
    name: str
    issuer: str
    client_id: str
    pkce: bool
    enabled: bool
    secret_set: bool
    secret_unreadable: bool
    locked: bool  # set by the variables
    linked_accounts: int
    homes: int  # homes that require it


def _environment_apps() -> list[dict[str, Any]]:
    apps: list[dict[str, Any]] = settings.SOCIALACCOUNT_PROVIDERS.get("openid_connect", {}).get(
        "APPS", []
    )
    return apps


def environment_slugs() -> set[str]:
    return {str(app.get("provider_id") or "openid_connect") for app in _environment_apps()}


def _counts(slug: str) -> tuple[int, int]:
    from allauth.socialaccount.models import SocialAccount

    from housecairn.homes.models import Home

    return (
        SocialAccount.objects.filter(provider=slug).count(),
        Home.objects.filter(required_provider=slug).count(),
    )


def _secret(provider: OidcProvider) -> tuple[str, bool]:
    """The client secret in clear, and whether the stored one could not be read."""
    if not provider.secret:
        return "", False
    try:
        return crypto.decrypt(provider.secret), False
    except crypto.SecretUnreadableError:
        logger.warning("Client secret of provider %s is unreadable.", provider.slug)
        return "", True


def describe_all() -> list[Declared]:
    """The providers set by variables first, then those of the interface."""
    out = []
    for app in _environment_apps():
        slug = str(app.get("provider_id") or "openid_connect")
        accounts, homes = _counts(slug)
        out.append(
            Declared(
                slug=slug,
                name=str(app.get("name", "")),
                issuer=str(app.get("settings", {}).get("server_url", "")),
                client_id=str(app.get("client_id", "")),
                pkce=True,
                enabled=True,
                secret_set=bool(app.get("secret")),
                secret_unreadable=False,
                locked=True,
                linked_accounts=accounts,
                homes=homes,
            )
        )
    for provider in OidcProvider.objects.all():
        out.append(describe(provider))
    return out


def describe(provider: OidcProvider) -> Declared:
    accounts, homes = _counts(provider.slug)
    return Declared(
        slug=provider.slug,
        name=provider.name,
        issuer=provider.issuer,
        client_id=provider.client_id,
        pkce=provider.pkce,
        enabled=provider.enabled,
        secret_set=bool(provider.secret),
        secret_unreadable=_secret(provider)[1],
        locked=False,
        linked_accounts=accounts,
        homes=homes,
    )


def social_apps(provider: str | None = None, client_id: str | None = None) -> list[Any]:
    """The enabled providers of the interface, as the apps django-allauth works with.

    Built in memory and never saved: allauth's own table of apps stays empty, and the
    secret is decrypted only for the request that needs it.
    """
    from allauth.socialaccount.models import SocialApp

    # The variables win: a provider they declare later under the same identifier hides
    # the one of the interface, rather than leaving allauth two apps for one identifier.
    rows = OidcProvider.objects.filter(enabled=True).exclude(slug__in=environment_slugs())
    if provider and provider != "openid_connect":
        rows = rows.filter(slug=provider)
    if client_id:
        rows = rows.filter(client_id=client_id)
    apps = []
    for row in rows:
        apps.append(
            SocialApp(
                provider="openid_connect",
                provider_id=row.slug,
                name=row.name,
                client_id=row.client_id,
                secret=_secret(row)[0],
                settings={"server_url": row.issuer, "oauth_pkce_enabled": row.pkce},
            )
        )
    return apps


def form_action_origins() -> list[str]:
    """Origins the sign-in form may lead to: those of the enabled providers' issuers."""
    try:
        # A savepoint: before `migrate` the table is missing, and a page must still render.
        with transaction.atomic():
            issuers = list(
                OidcProvider.objects.filter(enabled=True).values_list("issuer", flat=True)
            )
    except (DatabaseError, RuntimeError):
        return []
    origins = []
    for issuer in issuers:
        parts = urlsplit(issuer)
        if parts.scheme == "https" and parts.netloc:
            origins.append(f"https://{parts.netloc}")
    return sorted(set(origins))


# ---------- checks ----------


NAT64 = ipaddress.IPv6Network("64:ff9b::/96")  # RFC 6052: the IPv4 address is the last 32 bits


def _embedded_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 one carries: mapped, NAT64, 6to4 or Teredo (client)."""
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address in NAT64:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    return None


def _forbidden_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Addresses an issuer may not point to: the instance itself and link-local services.

    An IPv6 address that carries an IPv4 one is judged by the IPv4 address: through a
    NAT64 gateway or a 6to4 relay, it reaches that address. Private networks stay allowed:
    an identity provider often runs on the local network.
    """
    if isinstance(address, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(address)
        if embedded is not None:
            address = embedded
    return bool(
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def clean_issuer(value: Any) -> str:
    """The issuer, as an https:// address without query, fragment or credentials."""
    if not isinstance(value, str):
        raise ValidationError({"issuer": [_("Expected an https:// address.")]})
    text = value.strip().rstrip("/")
    try:
        parts = urlsplit(text)
        parts.port  # noqa: B018 - raises ValueError on a port out of range
    except ValueError:
        raise ValidationError({"issuer": [_("Expected an https:// address.")]}) from None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
        or len(text) > 255
        or any(c.isspace() for c in text)
    ):
        raise ValidationError(
            {"issuer": [_("Expected an https:// address, without query or credentials.")]}
        )
    try:
        literal = ipaddress.ip_address(parts.hostname)
    except ValueError:
        literal = None
    if literal is not None and _forbidden_address(literal):
        raise ValidationError({"issuer": [_("This address cannot be an identity provider.")]})
    return text


def _clean_text(field: str, value: Any, *, limit: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValidationError({field: [_("Expected text.")]})
    text = value.strip()
    if any(c in text for c in "\r\n") or len(text) > limit:
        raise ValidationError({field: [_("Expected a single line of text.")]})
    if required and not text:
        raise ValidationError({field: [_("This field is required.")]})
    return text


def _clean_slug(value: Any) -> str:
    from allauth.socialaccount.models import SocialAccount

    from housecairn.homes.models import Home

    slug = value.strip().lower() if isinstance(value, str) else ""
    if not SLUG.match(slug):
        raise ValidationError(
            {
                "slug": [
                    _(
                        "From 2 to 32 lowercase letters, digits or hyphens, "
                        "starting with a letter or a digit."
                    )
                ]
            }
        )
    if (
        slug in environment_slugs()
        or slug == "openid_connect"
        or OidcProvider.all_objects.filter(slug=slug).exists()
        or SocialAccount.objects.filter(provider=slug).exists()
        or Home.objects.filter(required_provider=slug).exists()
    ):
        # Never given twice: identities and homes that point to it must not pass to
        # another provider.
        raise ValidationError({"slug": [_("This identifier is or was already used.")]})
    return slug


def _bool(field: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValidationError({field: [_("Expected true or false.")]})
    return value


def _clean(field: str, value: Any) -> Any:
    if field == "name":
        return _clean_text(field, value, limit=64)
    if field == "issuer":
        return clean_issuer(value)
    if field == "client_id":
        return _clean_text(field, value, limit=255)
    if field == "secret":
        return _clean_text(field, value, limit=1024, required=False)
    return _bool(field, value)


def keeps_a_way_to_sign_in(user: User, *, without: str) -> bool:
    """Whether `user` can still sign in once the provider `without` is gone or disabled."""
    from allauth.mfa.models import Authenticator
    from allauth.mfa.webauthn.internal.auth import WebAuthn
    from allauth.socialaccount.models import SocialAccount

    if user.has_usable_password():
        return True
    # A passkey: a security key that holds the account (resident), so that it signs in alone.
    # A key that is only a second factor does not count.
    keys = Authenticator.objects.filter(user=user, type=Authenticator.Type.WEBAUTHN)
    if any(WebAuthn(key).is_passwordless for key in keys):
        return True
    usable = environment_slugs() | set(
        OidcProvider.objects.filter(enabled=True)
        .exclude(slug=without)
        .values_list("slug", flat=True)
    )
    return bool(SocialAccount.objects.filter(user=user, provider__in=usable).exists())


LAST_WAY = gettext_lazy(
    "This is your last way to sign in: set a password or a passkey, or link another "
    "provider, first."
)


SECRET_FOR_NEW_ISSUER = gettext_lazy(
    "The client secret is not kept for another issuer: enter it again, or disable the "
    "provider to save the new issuer without a secret."
)


def _guard(actor: User, slug: str, field: str = "enabled") -> None:
    if not keeps_a_way_to_sign_in(actor, without=slug):
        raise ValidationError({field: [str(LAST_WAY)]})


# ---------- changes ----------


def _shown(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)[:200] or "(empty)"


def create(actor: User, data: dict[str, Any]) -> OidcProvider:
    _require_admin(actor)
    errors: dict[str, list[str]] = {}
    clean: dict[str, Any] = {}
    for field in ("slug", "name", "issuer", "client_id", "secret", "pkce", "enabled"):
        if field not in data:
            if field in ("secret", "pkce", "enabled"):
                continue
            errors[field] = [_("This field is required.")]
            continue
        try:
            clean[field] = (
                _clean_slug(data[field]) if field == "slug" else _clean(field, data[field])
            )
        except ValidationError as exc:
            errors.update(exc.message_dict)
    if errors:
        raise ValidationError(errors)
    secret = clean.pop("secret", "")
    with transaction.atomic():
        provider: OidcProvider = OidcProvider.objects.create(
            **clean, secret=crypto.encrypt(secret) if secret else "", updated_by=actor
        )
        audit.record("provider.created", actor=actor, provider=provider.slug)
        if secret:
            audit.record("provider.secret_changed", actor=actor, provider=provider.slug)
    return provider


def update(actor: User, provider: OidcProvider, changes: dict[str, Any]) -> list[str]:
    """Apply `changes`; returns the fields that changed. A secret is never audited."""
    _require_admin(actor)
    errors: dict[str, list[str]] = {}
    clean: dict[str, Any] = {}
    for field, value in changes.items():
        if field == "slug":
            if value != provider.slug:
                errors["slug"] = [_("The identifier of a provider never changes.")]
            continue
        if field not in (*EDITABLE, "secret"):
            errors[field] = [_("Unknown field.")]
            continue
        try:
            clean[field] = _clean(field, value)
        except ValidationError as exc:
            errors.update(exc.message_dict)
    if errors:
        raise ValidationError(errors)
    changed: list[str] = []
    with transaction.atomic():
        provider = OidcProvider.objects.select_for_update().get(pk=provider.pk)
        new_issuer = "issuer" in clean and clean["issuer"] != provider.issuer
        if new_issuer and _counts(provider.slug)[0]:
            raise ValidationError(
                {
                    "issuer": [
                        _(
                            "Accounts are linked to this provider: another issuer could sign "
                            "in as them. Declare a new provider for the new issuer."
                        )
                    ]
                }
            )
        # The secret goes, at sign-in, to the token endpoint the issuer names: it never
        # follows the provider to another issuer. Kept only if typed in the same request.
        clear_secret = new_issuer and bool(provider.secret) and not clean.get("secret")
        if clear_secret and clean.get("enabled", provider.enabled):
            raise ValidationError({"secret": [str(SECRET_FOR_NEW_ISSUER)]})
        if clean.get("enabled") is False and provider.enabled:
            _guard(actor, provider.slug)
        elif provider.enabled:
            # What signs people in: a wrong issuer, client or secret breaks it like disabling.
            touched = [
                f
                for f in ("issuer", "client_id")
                if f in clean and clean[f] != getattr(provider, f)
            ]
            if clean.get("secret"):
                touched.append("secret")
            if touched:
                _guard(actor, provider.slug, field=touched[0])
        if clear_secret:
            provider.secret = ""
            changed.append("secret")
            audit.record("provider.secret_cleared", actor=actor, provider=provider.slug)
        for field, value in clean.items():
            if field == "secret":
                if value:
                    provider.secret = crypto.encrypt(value)
                    changed.append(field)
                    audit.record("provider.secret_changed", actor=actor, provider=provider.slug)
                continue
            before = getattr(provider, field)
            if value == before:
                continue
            setattr(provider, field, value)
            changed.append(field)
            audit.record(
                "provider.changed",
                actor=actor,
                provider=provider.slug,
                setting=field,
                old=_shown(before),
                new=_shown(value),
            )
        if changed:
            provider.updated_by = actor
            provider.save()
    return changed


def delete(actor: User, provider: OidcProvider) -> None:
    """Remove a provider; its identifier stays reserved. Refused while a home requires it."""
    _require_admin(actor)
    with transaction.atomic():
        provider = OidcProvider.objects.select_for_update().get(pk=provider.pk)
        homes = _counts(provider.slug)[1]
        if homes:
            raise ValidationError(
                {
                    "slug": [
                        _(
                            "%(count)s home(s) require this provider: it cannot be deleted. "
                            "Disable it instead; the owners, or you from the instance page, "
                            "can then remove the requirement."
                        )
                        % {"count": homes}
                    ]
                }
            )
        if provider.enabled:
            _guard(actor, provider.slug)
        provider.enabled = False
        provider.secret = ""
        provider.updated_by = actor
        provider.save()
        provider.soft_delete()
        audit.record("provider.deleted", actor=actor, provider=provider.slug)


# ---------- the test button ----------

CHECK_MESSAGES = {
    "ok": gettext_lazy("The issuer answers with a valid OpenID configuration."),
    "invalid": gettext_lazy("The issuer is not a valid https:// address."),
    "blocked": gettext_lazy("The issuer resolves to an address the instance does not call."),
    "unreachable": gettext_lazy("The issuer could not be reached."),
    "tls": gettext_lazy("The secure connection to the issuer failed: check its certificate."),
    "not_found": gettext_lazy("The issuer has no OpenID configuration at the usual address."),
    "not_oidc": gettext_lazy("The issuer's answer is not a valid OpenID configuration."),
    "mismatch": gettext_lazy("The OpenID configuration names another issuer."),
}


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """An HTTPS connection to an address already checked, verified against the host name."""

    def __init__(self, address: str, host: str, port: int) -> None:
        super().__init__(
            host, port, timeout=DISCOVERY_TIMEOUT, context=ssl.create_default_context()
        )
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


def _get(address: str, port: int, host: str, path: str) -> tuple[int, bytes]:
    """GET `path` over TLS from `address`, the certificate checked against `host`.

    The connection goes to the address that was checked (no second resolution, so no
    rebinding), follows no redirect, and reads at most `DISCOVERY_MAX_BYTES` + 1.
    """
    connection = _PinnedHTTPSConnection(address, host, port)
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        return response.status, response.read(DISCOVERY_MAX_BYTES + 1)
    finally:
        connection.close()


def discover(issuer: str) -> str:
    """Fetch the issuer's OpenID configuration and check it; a code from CHECK_MESSAGES."""
    try:
        issuer = clean_issuer(issuer)
    except ValidationError:
        return "invalid"
    parts = urlsplit(issuer)
    host = parts.hostname or ""
    port = parts.port or 443
    try:
        addresses = _resolve(host, port)
    except (OSError, UnicodeError):
        return "unreachable"
    if not addresses or any(_forbidden_address(ipaddress.ip_address(a)) for a in addresses):
        return "blocked"
    try:
        status, body = _get(addresses[0], port, host, parts.path + DISCOVERY_PATH)
    except ssl.SSLError:
        return "tls"
    except (http.client.HTTPException, OSError):
        return "unreachable"
    if status != 200:
        return "not_found"
    if len(body) > DISCOVERY_MAX_BYTES:
        return "not_oidc"
    try:
        config = json.loads(body)
    except (ValueError, UnicodeError):
        return "not_oidc"
    if not isinstance(config, dict) or not all(
        isinstance(config.get(key), str) and config[key].startswith("https://")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri")
    ):
        return "not_oidc"
    if str(config.get("issuer", "")).rstrip("/") != issuer:
        return "mismatch"
    return "ok"


def check(actor: User, issuer: str) -> tuple[bool, str]:
    """The test button: never required to save, and it says only one of a few words."""
    _require_admin(actor)
    code = discover(issuer)
    return code == "ok", str(CHECK_MESSAGES[code])
