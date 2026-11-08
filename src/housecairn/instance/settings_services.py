"""Changing the instance settings: validation, storage, audit (docs/adr/0031).

Web and API both come through here. Who may call it, and whether they signed in recently,
is decided by the caller; the rules that keep the instance reachable are decided here.
"""

import json
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from housecairn.accounts.models import User
from housecairn.accounts.services import is_instance_admin
from housecairn.audit import services as audit
from housecairn.instance import config, crypto, mail, registry
from housecairn.instance.models import SettingValue

MAX_AUDIT_VALUE = 200


def _require_admin(actor: Any) -> None:
    if not is_instance_admin(actor):
        raise PermissionDenied


def locked_message(setting: registry.Setting) -> str:
    return _("Set by the variable %(env)s: change it there.") % {"env": setting.env}


def _shown(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(value)
    text = "" if value is None else str(value)
    return (text or "(empty)")[:MAX_AUDIT_VALUE]


def _validate(changes: dict[str, Any]) -> dict[str, Any]:
    """The new values, checked one by one and together; ValidationError names each failure."""
    errors: dict[str, list[str]] = {}
    clean: dict[str, Any] = {}
    for key, raw in changes.items():
        setting = registry.SETTINGS.get(key)
        if setting is None:
            errors[key] = [_("Unknown setting.")]
        elif config.is_locked(key):
            errors[key] = [locked_message(setting)]
        else:
            try:
                clean[key] = setting.coerce(raw)
            except ValueError as exc:
                errors[key] = [str(exc)]
            else:
                if setting.secret and not clean[key]:
                    errors[key] = [_("A secret cannot be empty: reset it to remove it.")]
    if not errors:
        errors = _validate_together(clean)
    if errors:
        raise ValidationError(errors)
    return clean


def _validate_together(clean: dict[str, Any]) -> dict[str, list[str]]:
    """The rules between settings, on the state that `clean` would leave.

    `clean` holds the values about to be in force (a change, or the value a reset falls
    back to); the other settings keep the value they have now. Every write goes through
    here, so that no change and no reset leaves an incoherent instance.
    """

    def effective(key: str) -> Any:
        return clean[key] if key in clean else config.get_setting(key)

    errors: dict[str, list[str]] = {}
    if effective("signup_open") and not effective("email_host"):
        key = "signup_open" if "signup_open" in clean else "email_host"
        errors[key] = [
            _(
                "Open sign-up verifies addresses by email: set the SMTP server first, "
                "or keep sign-up closed."
            )
        ]
    return errors


def update(actor: User, changes: dict[str, Any]) -> list[str]:
    """Apply `changes` (key to new value) all together; returns the keys that changed.

    A secret in `changes` is stored encrypted and never audited. A value equal to the
    default is stored as no value, so that the setting then follows the default.
    """
    _require_admin(actor)
    clean = _validate(changes)
    changed: list[str] = []
    with transaction.atomic():
        for key, value in clean.items():
            setting = registry.SETTINGS[key]
            before = config.describe(key)
            if setting.secret:
                SettingValue.objects.update_or_create(
                    key=key,
                    defaults={
                        "value": crypto.encrypt(value),
                        "is_secret": True,
                        "updated_by": actor,
                    },
                )
                audit.record("settings.secret_changed", actor=actor, setting=key)
            else:
                if value == before.value:
                    continue
                if value == setting.default:
                    SettingValue.objects.filter(key=key).delete()
                else:
                    SettingValue.objects.update_or_create(
                        key=key,
                        defaults={
                            "value": json.dumps(value),
                            "is_secret": False,
                            "updated_by": actor,
                        },
                    )
                audit.record(
                    "settings.changed",
                    actor=actor,
                    setting=key,
                    old=_shown(before.value),
                    new=_shown(value),
                )
            changed.append(key)
    config.invalidate()
    config.refresh()
    return changed


def reset(actor: User, key: str) -> bool:
    """Back to the default: the stored value is removed. True if there was one.

    The state it leaves is checked like a change: restoring no mail server while sign-up
    is open (in the database or by variable) is refused with the same message.
    """
    _require_admin(actor)
    setting = registry.SETTINGS.get(key)
    if setting is None:
        raise ValidationError({key: [_("Unknown setting.")]})
    if config.is_locked(key):
        raise ValidationError({key: [locked_message(setting)]})
    if config.source(key) == config.Source.DATABASE:
        errors = _validate_together({key: config.without_database(key)})
        if errors:
            raise ValidationError(errors)
    with transaction.atomic():
        deleted, _unused = SettingValue.objects.filter(key=key).delete()
        if deleted:
            audit.record("settings.reset", actor=actor, setting=key)
    config.invalidate()
    config.refresh()
    return bool(deleted)


EMAIL_TEST_MESSAGES = {
    "ok": _("Connected to the mail server."),
    "no_server": _("No SMTP server is set."),
    "auth": _("The server refused the user name or password."),
    "tls": _("The secure connection could not be set up: check STARTTLS and the port."),
    "unreachable": _("The mail server could not be reached or refused the connection."),
}


def check_email(actor: User) -> tuple[bool, str]:
    """Connect to the mail server with the settings in force; nothing is sent."""
    _require_admin(actor)
    code = mail.check_connection()
    return code == "ok", str(EMAIL_TEST_MESSAGES[code])
