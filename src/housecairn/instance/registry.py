"""The settings an administrator can change in the interface (docs/adr/0035).

Each one is paired with an environment variable: the variable wins and locks the
field, otherwise the value stored in the database, otherwise the default. This
module only describes the settings and parses their values; it imports no model,
so that `housecairn.settings` can use it before the database exists. Reading a
value anywhere else goes through `housecairn.instance.config.get_setting`.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from django.utils.functional import Promise
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _

# django-environ's own list of true strings, so that an existing environment keeps its meaning.
_TRUE = frozenset({"true", "on", "ok", "y", "yes", "1"})
_FALSE = frozenset({"false", "off", "n", "no", "0"})


class Kind(StrEnum):
    BOOL = "boolean"
    INT = "integer"
    STR = "string"
    CHOICE = "choice"
    LIST = "list"
    SECRET = "secret"  # noqa: S105 - a kind, not a password


class Reload(StrEnum):
    """When a change takes effect."""

    LIVE = "live"  # at once here, within a few seconds on the other processes
    RESTART = "restart"


class Section(StrEnum):
    ADDRESS = "address"
    SIGNUP = "signup"
    INVITATIONS = "invitations"
    EMAIL = "email"


SECTION_LABELS: dict[Section, Promise] = {
    Section.ADDRESS: _("Public address"),
    Section.SIGNUP: _("Sign-up"),
    Section.INVITATIONS: _("Invitations"),
    Section.EMAIL: _("Outgoing email"),
}


@dataclass(frozen=True)
class Setting:
    key: str
    env: str  # the environment variable that pairs with it
    django_name: str  # the Django setting that holds the value read from the environment
    kind: Kind
    section: Section
    label: Promise
    help: Promise
    default: Any
    reload: Reload = Reload.LIVE
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()
    check: Callable[[Any], None] | None = field(default=None, compare=False)
    # False: the check applies to what is typed in the interface, not to an existing variable.
    strict_env: bool = True

    @property
    def secret(self) -> bool:
        return self.kind is Kind.SECRET

    def parse_environment(self, raw: str) -> Any:
        """The value of the variable, as a Python value; ValueError if it is not valid."""
        text = raw.strip()
        if self.kind is Kind.BOOL:
            if text.lower() in _TRUE:
                return True
            if text.lower() in _FALSE:
                return False
            raise ValueError(_("Expected true or false."))
        return self.coerce(text, check=self.strict_env)

    def coerce(self, value: Any, *, check: bool = True) -> Any:
        """A valid value, from a form, the API or storage; ValueError with a message if not."""
        kind = self.kind
        if kind is Kind.BOOL:
            if isinstance(value, bool):
                return value
            raise ValueError(_("Expected true or false."))
        if kind is Kind.INT:
            if isinstance(value, bool) or not isinstance(value, int | str):
                raise ValueError(_("Expected a whole number."))
            try:
                number = int(str(value).strip())
            except ValueError:
                raise ValueError(_("Expected a whole number.")) from None
            if self.minimum is not None and number < self.minimum:
                raise ValueError(format_lazy(_("Must be at least {n}."), n=self.minimum))
            if self.maximum is not None and number > self.maximum:
                raise ValueError(format_lazy(_("Must be at most {n}."), n=self.maximum))
            return number
        if kind is Kind.LIST:
            if isinstance(value, str):
                value = value.replace("\n", ",").split(",")
            if not isinstance(value, list | tuple):
                raise ValueError(_("Expected a list of domains."))
            items = [str(v).strip().lower().lstrip("@") for v in value if str(v).strip()]
            for item in items:
                if not _is_domain(item):
                    raise ValueError(format_lazy(_("{item} is not a domain name."), item=item))
            return list(dict.fromkeys(items))
        if not isinstance(value, str):
            raise ValueError(_("Expected text."))
        text = value.strip()
        if "\n" in text or "\r" in text or len(text) > 1024:
            raise ValueError(_("Expected a single line of text."))
        if kind is Kind.CHOICE and text not in self.choices:
            raise ValueError(
                format_lazy(_("Must be one of: {choices}."), choices=", ".join(self.choices))
            )
        if check and self.check is not None and text:
            self.check(text)
        return text.rstrip("/") if self.key == "site_url" else text


def _is_domain(name: str) -> bool:
    labels = name.split(".")
    return 0 < len(name) <= 253 and all(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(c.isalnum() or c == "-" for c in label)
        for label in labels
    )


def _check_site_url(value: str) -> None:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path.strip("/"):
        raise ValueError(_("Must be an http:// or https:// address without a path."))
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError(_("Must be an http:// or https:// address without a path."))


def _check_host(value: str) -> None:
    if not all(c.isalnum() or c in ".-_:[]" for c in value):
        raise ValueError(_("Must be a host name or an address."))


def _check_from(value: str) -> None:
    if "@" not in value or ("<" in value) != (">" in value):
        raise ValueError(_("Must be an address, such as HouseCairn <noreply@example.com>."))


_SETTINGS = (
    Setting(
        "site_url",
        "HOUSECAIRN_SITE_URL",
        "HOUSECAIRN_SITE_URL",
        Kind.STR,
        Section.ADDRESS,
        _("Public address"),
        _(
            "Scheme and host of the instance, such as https://home.example.com, used for links "
            "in emails. Empty: the address of the request."
        ),
        "",
        check=_check_site_url,
    ),
    Setting(
        "signup_open",
        "HOUSECAIRN_SIGNUP_OPEN",
        "HOUSECAIRN_SIGNUP_OPEN",
        Kind.BOOL,
        Section.SIGNUP,
        _("Open sign-up"),
        _("Anyone may create an account from the sign-up page. Needs outgoing email."),
        False,
    ),
    Setting(
        "oidc_signup",
        "HOUSECAIRN_OIDC_SIGNUP",
        "HOUSECAIRN_OIDC_SIGNUP",
        Kind.CHOICE,
        Section.SIGNUP,
        _("Sign-up through single sign-on"),
        _(
            "closed: only invited people and the first administrator; "
            "open: anyone the provider accepts."
        ),
        "closed",
        choices=("closed", "open"),
    ),
    Setting(
        "signup_allowed_domains",
        "HOUSECAIRN_SIGNUP_ALLOWED_DOMAINS",
        "HOUSECAIRN_SIGNUP_ALLOWED_DOMAINS",
        Kind.LIST,
        Section.SIGNUP,
        _("Allowed domains"),
        _("Comma-separated. If set, only these domains may sign up."),
        [],
    ),
    Setting(
        "signup_blocked_domains",
        "HOUSECAIRN_SIGNUP_BLOCKED_DOMAINS",
        "HOUSECAIRN_SIGNUP_BLOCKED_DOMAINS",
        Kind.LIST,
        Section.SIGNUP,
        _("Blocked domains"),
        _("Comma-separated. These domains may not sign up."),
        [],
    ),
    Setting(
        "signup_pow_bits",
        "HOUSECAIRN_SIGNUP_POW_BITS",
        "HOUSECAIRN_SIGNUP_POW_BITS",
        Kind.INT,
        Section.SIGNUP,
        _("Anti-robot work"),
        _("Zero bits the browser must find before signing up, from 8 to 24; 16 takes a second."),
        16,
        minimum=8,
        maximum=24,
    ),
    Setting(
        "invitation_lifetime_days",
        "HOUSECAIRN_INVITATION_LIFETIME_DAYS",
        "HOUSECAIRN_INVITATION_LIFETIME_DAYS",
        Kind.INT,
        Section.INVITATIONS,
        _("Invitation lifetime (days)"),
        _("Days an invitation link stays valid, from 1 to 90. Applies to new links."),
        7,
        minimum=1,
        maximum=90,
    ),
    Setting(
        "email_host",
        "EMAIL_HOST",
        "EMAIL_HOST",
        Kind.STR,
        Section.EMAIL,
        _("SMTP server"),
        _("Host name of the outgoing mail server. Empty: email is off."),
        "",
        check=_check_host,
        strict_env=False,
    ),
    Setting(
        "email_port",
        "EMAIL_PORT",
        "EMAIL_PORT",
        Kind.INT,
        Section.EMAIL,
        _("SMTP port"),
        _("587 for STARTTLS, 465 for TLS from the first byte."),
        587,
        minimum=1,
        maximum=65535,
    ),
    Setting(
        "email_use_tls",
        "EMAIL_USE_TLS",
        "EMAIL_USE_TLS",
        Kind.BOOL,
        Section.EMAIL,
        _("STARTTLS"),
        _("Upgrade the connection with STARTTLS. Ignored when TLS from the first byte is on."),
        True,
    ),
    Setting(
        "email_use_ssl",
        "EMAIL_USE_SSL",
        "EMAIL_USE_SSL",
        Kind.BOOL,
        Section.EMAIL,
        _("TLS from the first byte"),
        _("Usually with port 465."),
        False,
    ),
    Setting(
        "email_host_user",
        "EMAIL_HOST_USER",
        "EMAIL_HOST_USER",
        Kind.STR,
        Section.EMAIL,
        _("SMTP user name"),
        _("Empty: no authentication."),
        "",
    ),
    Setting(
        "email_host_password",
        "EMAIL_HOST_PASSWORD",
        "EMAIL_HOST_PASSWORD",
        Kind.SECRET,
        Section.EMAIL,
        _("SMTP password"),
        _("Write only: it is never shown again."),
        "",
    ),
    Setting(
        "email_timeout",
        "EMAIL_TIMEOUT",
        "EMAIL_TIMEOUT",
        Kind.INT,
        Section.EMAIL,
        _("SMTP timeout (seconds)"),
        _("How long to wait for the mail server, from 1 to 120."),
        15,
        minimum=1,
        maximum=120,
    ),
    Setting(
        "default_from_email",
        "DEFAULT_FROM_EMAIL",
        "DEFAULT_FROM_EMAIL",
        Kind.STR,
        Section.EMAIL,
        _("Sender address"),
        _("Address emails come from, such as HouseCairn <noreply@example.com>."),
        "HouseCairn <noreply@localhost>",
        check=_check_from,
        strict_env=False,
    ),
)

SETTINGS: dict[str, Setting] = {s.key: s for s in _SETTINGS}


def in_section(section: Section) -> list[Setting]:
    return [s for s in _SETTINGS if s.section is section]


# What stays in the environment: needed before there is a database, or able to lock the
# administrator out. Shown, without secrets, on the read-only "Server" part of the screen.
SERVER_VARIABLES: tuple[tuple[str, Promise], ...] = (
    ("SECRET_KEY", _("Secret key of the instance")),
    ("ALLOWED_HOSTS", _("Host names the instance answers to")),
    ("CSRF_TRUSTED_ORIGINS", _("Trusted origins for forms")),
    ("DATABASE_URL", _("Database")),
    ("HOUSECAIRN_DATA_DIR", _("Data directory")),
    ("HOUSECAIRN_BEHIND_TLS_PROXY", _("Behind a TLS reverse proxy")),
    ("HOUSECAIRN_FORWARDED_ALLOW_IPS", _("Trusted reverse proxies")),
    ("DEBUG", _("Debug mode")),
    ("HOUSECAIRN_TASK_WORKERS", _("Task worker processes")),
    ("HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL", _("First administrator")),
)


def _expected(setting: Setting) -> str:
    """What the variable should hold, in plain English: it is shown while Django starts."""
    if setting.kind is Kind.BOOL:
        return "true or false"
    if setting.kind is Kind.INT:
        return f"a whole number from {setting.minimum} to {setting.maximum}"
    if setting.kind is Kind.CHOICE:
        return "one of " + ", ".join(setting.choices)
    if setting.kind is Kind.LIST:
        return "domain names separated by commas"
    if setting.key == "site_url":
        return "an http:// or https:// address without a path"
    return "a single line of text"


@dataclass(frozen=True)
class Environment:
    values: dict[str, Any]
    locked: frozenset[str]


def read_environment(environ: dict[str, str] | None = None) -> Environment:
    """Parse the variables of every setting, once, when Django starts.

    A variable that is set and not empty wins and locks its field. An invalid one stops
    the start-up, as before: an operator must see the mistake.
    """
    source = os.environ if environ is None else environ
    values: dict[str, Any] = {}
    locked: set[str] = set()
    for setting in _SETTINGS:
        raw = source.get(setting.env, "")
        if raw.strip():
            try:
                values[setting.key] = setting.parse_environment(raw)
            except ValueError as exc:
                # No translated message here: Django is still loading its settings.
                raise ImproperlyConfigured(
                    f"{setting.env} is not valid: expected {_expected(setting)}."
                ) from exc
            locked.add(setting.key)
        else:
            values[setting.key] = setting.default
    return Environment(values, frozenset(locked))
