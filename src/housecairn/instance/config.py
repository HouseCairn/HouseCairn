"""Reading the settings that the interface and the environment share (docs/adr/0031).

`get_setting(key)` is the one way the code reads them. Resolution order: the environment
variable if it is set (the field is then locked), else the value stored in the database,
else the default. Values come from the database through a snapshot that lives a few
seconds in each process, so a change made through one process reaches the others without a
restart.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import DatabaseError, transaction

from housecairn.instance import crypto, registry
from housecairn.instance.registry import Setting

logger = logging.getLogger("housecairn.settings")

# Seconds another process may take to see a change.
SNAPSHOT_SECONDS = 5.0

_lock = threading.Lock()
_snapshot: dict[str, tuple[str, bool]] | None = None
# The last snapshot read from the database, kept when a later read fails.
_last_good: dict[str, tuple[str, bool]] | None = None
_loaded_at = 0.0

# What the settings held before the database changed them: restored when a value is reset.
_ORIGINAL = {
    name: getattr(settings, name, None)
    for name in ("ACCOUNT_EMAIL_VERIFICATION", "ACCOUNT_EMAIL_NOTIFICATIONS")
}


_applied: set[str] = set()


def invalidate() -> None:
    """Forget the snapshot: the next read loads it again. Called after every write."""
    global _snapshot
    with _lock:
        _snapshot = None


def reset() -> None:
    """Back to the start-up state (tests)."""
    global _last_good
    invalidate()
    with _lock:
        _last_good = None
    for name in _applied:
        setattr(settings, name, _ORIGINAL[name])
    _applied.clear()


def _load() -> dict[str, tuple[str, bool]] | None:
    """The stored values, or None when the database cannot be read."""
    from housecairn.instance.models import SettingValue

    try:
        # A savepoint, so that a missing table (before `migrate`) cannot abort a transaction.
        with transaction.atomic():
            rows = list(SettingValue.objects.values_list("key", "value", "is_secret"))
    except (DatabaseError, RuntimeError):
        # No table yet (before `migrate`), no database, a locked database, or a context
        # that forbids queries.
        return None
    return {key: (value, secret) for key, value, secret in rows}


def _current() -> dict[str, tuple[str, bool]]:
    """The snapshot in force, loaded again when it is older than `SNAPSHOT_SECONDS`.

    A failed read keeps the last snapshot that was read (the settings do not vanish
    because the database was busy once), or, before any, the environment and defaults
    alone; it is tried again after the same delay.
    """
    global _snapshot, _last_good, _loaded_at
    with _lock:
        if _snapshot is not None and time.monotonic() - _loaded_at < SNAPSHOT_SECONDS:
            return _snapshot
    loaded = _load()
    with _lock:
        if loaded is None:
            logger.warning(
                "Settings table not readable: using the last values read, "
                "or the environment and defaults."
            )
            loaded = _last_good if _last_good is not None else {}
        else:
            _last_good = loaded
        _snapshot, _loaded_at = loaded, time.monotonic()
    _apply_derived(loaded)
    return loaded


def is_locked(key: str) -> bool:
    """Whether an environment variable sets this one."""
    return key in settings.HOUSECAIRN_ENV_LOCKED


def _static(setting: Setting) -> Any:
    return getattr(settings, setting.django_name)


def without_database(key: str) -> Any:
    """The value this setting would have with nothing stored: its variable, else its default."""
    return _static(registry.SETTINGS[key])


def _stored(setting: Setting, row: tuple[str, bool]) -> Any:
    value, is_secret = row
    if setting.secret:
        return crypto.decrypt(value) if is_secret else None
    return setting.coerce(json.loads(value))


def get_setting(key: str) -> Any:
    """The value in force: variable, else database, else default."""
    setting = registry.SETTINGS[key]
    if is_locked(key):
        return _static(setting)
    row = _current().get(key)
    if row is not None:
        try:
            stored = _stored(setting, row)
        except (crypto.SecretUnreadableError, ValueError, TypeError):
            logger.warning("Stored value of setting %s is unreadable: using the default.", key)
        else:
            if stored is not None:
                return stored
    return _static(setting)


class Source:
    ENVIRONMENT = "environment"
    DATABASE = "database"
    DEFAULT = "default"


def source(key: str) -> str:
    if is_locked(key):
        return Source.ENVIRONMENT
    return Source.DATABASE if key in _current() else Source.DEFAULT


@dataclass(frozen=True)
class State:
    """What a screen or the API says about one setting; never a secret."""

    setting: Setting
    value: Any  # None for a secret
    source: str
    is_set: bool  # for a secret: whether there is one
    unreadable: bool  # a stored secret that the instance's key cannot decrypt

    @property
    def locked(self) -> bool:
        return self.source == Source.ENVIRONMENT


def describe(key: str) -> State:
    setting = registry.SETTINGS[key]
    origin = source(key)
    unreadable = False
    if setting.secret:
        row = _current().get(key) if origin == Source.DATABASE else None
        if row is not None:
            try:
                crypto.decrypt(row[0])
            except crypto.SecretUnreadableError:
                unreadable = True
        return State(setting, None, origin, bool(get_setting(key)), unreadable)
    value = get_setting(key)
    return State(setting, value, origin, bool(value), False)


def _apply_derived(snapshot: dict[str, tuple[str, bool]]) -> None:
    """Keep the Django and allauth settings that follow a setting in step with the database.

    The verification of addresses follows open sign-up, and security alerts follow the mail
    server. Only a value the database sets is applied; when it is removed, the start-up value
    comes back.
    """
    if not settings.HOUSECAIRN_EMAIL_VERIFICATION_PINNED:
        _follow(
            snapshot,
            "signup_open",
            "ACCOUNT_EMAIL_VERIFICATION",
            lambda: "mandatory" if get_setting("signup_open") else "optional",
        )
    _follow(
        snapshot,
        "email_host",
        "ACCOUNT_EMAIL_NOTIFICATIONS",
        lambda: bool(get_setting("email_host")),
    )


def _follow(
    snapshot: dict[str, tuple[str, bool]], key: str, django_name: str, derive: Callable[[], Any]
) -> None:
    if key in snapshot and not is_locked(key):
        setattr(settings, django_name, derive())
        _applied.add(django_name)
    elif django_name in _applied:
        setattr(settings, django_name, _ORIGINAL[django_name])
        _applied.discard(django_name)


def refresh() -> None:
    """Load the snapshot if it is missing or old, and apply what follows from it."""
    _current()
