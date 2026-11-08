"""Rules of notification channels and reminder preferences (docs/adr/0002, 0043).

Web views and API views call these functions. A channel is read and changed by its owner
only: the views look it up among `channels_of(request.user)`, so anyone else, an
administrator of the instance included, gets the same 404.
"""

import time
import zoneinfo
from typing import Any

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from housecairn.accounts.models import User
from housecairn.instance.config import get_setting
from housecairn.notifications import outbound
from housecairn.notifications.models import MAX_CHANNELS, Channel, Preference

AnyUser = User | AnonymousUser

PREFERENCE_FIELDS = frozenset(
    {"days_before", "send_at", "quiet_start", "quiet_end", "digest", "language", "time_zone"}
)
CHANNEL_FIELDS = frozenset({"name", "enabled"})
TESTS_PER_MINUTE = 5

REFUSALS = {
    "invalid": gettext_lazy("This is not an Apprise address, such as ntfys://ntfy.sh/topic."),
    "scheme": gettext_lazy(
        "This kind of channel is not offered. Use ntfy, Gotify, Telegram, Signal, Matrix, "
        "email, Discord, Slack, Pushover, Mattermost or Apprise API."
    ),
    "options": gettext_lazy("These options make the instance read a file: remove them."),
    "fields": gettext_lazy(
        "Options that add headers or fields to the request (+name, -name, :name) are not "
        "accepted: remove them."
    ),
    "address": gettext_lazy("The instance does not send to this address."),
}
ADDED = gettext_lazy("Channel added. Send a test to check it.")
SAVED = gettext_lazy("Saved.")
DELETED = gettext_lazy("Channel deleted.")
TEST_RESULTS = {
    True: gettext_lazy("The test message was sent."),
    False: gettext_lazy("The test message could not be sent: check the address and the service."),
}


def is_enabled() -> bool:
    return bool(get_setting("notifications_enabled"))


def _person(actor: AnyUser) -> User:
    if not isinstance(actor, User) or not actor.is_authenticated:
        raise PermissionDenied
    return actor


def _require_owner(actor: AnyUser, channel: Channel) -> User:
    user = _person(actor)
    if channel.user_id != user.pk:
        raise PermissionDenied
    return user


def _require_enabled() -> None:
    if not is_enabled():
        raise ValidationError(_("Notifications are turned off on this instance."))


def _clean_name(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text or len(text) > 60 or any(not c.isprintable() for c in text):
        raise ValidationError({"name": [_("Give a name of 1 to 60 characters.")]})
    return text


# ---------- channels ----------


def channels_of(user: AnyUser) -> models.QuerySet[Channel]:
    if not isinstance(user, User) or not user.is_authenticated:
        return Channel.objects.none()
    return Channel.objects.filter(user=user)


@transaction.atomic
def add_channel(actor: AnyUser, *, name: Any, url: Any) -> Channel:
    """A new channel of the person signed in; the address is checked, then sealed."""
    user = _person(actor)
    _require_enabled()
    clean_name = _clean_name(name)
    list(User.objects.select_for_update().filter(pk=user.pk))  # counted once at a time
    if channels_of(user).count() >= MAX_CHANNELS:
        raise ValidationError(_("At most %(n)d channels.") % {"n": MAX_CHANNELS})
    try:
        parsed = outbound.parse(url)
    except outbound.RefusedError as refused:
        raise ValidationError({"url": [REFUSALS[str(refused)]]}) from None
    channel: Channel = Channel.objects.create(
        user=user,
        name=clean_name,
        url=outbound.seal(url),
        scheme=parsed.scheme,
        service=parsed.service,
    )
    return channel


def update_channel(actor: AnyUser, channel: Channel, **changes: Any) -> Channel:
    """Rename, turn off or on. The address cannot change: delete the channel and add another."""
    _require_owner(actor, channel)
    unknown = set(changes) - CHANNEL_FIELDS
    if unknown:
        raise ValueError(f"Cannot change: {', '.join(sorted(unknown))}")
    if "name" in changes:
        channel.name = _clean_name(changes["name"])
    if "enabled" in changes:
        channel.enabled = bool(changes["enabled"])
    channel.save(update_fields=[*changes, "updated_at"])
    return channel


def delete_channel(actor: AnyUser, channel: Channel) -> None:
    """For good, its sealed address with it."""
    _require_owner(actor, channel)
    channel.delete()


def _consume_test(user: User) -> bool:
    key = f"housecairn:notifications:test:{user.pk}:{int(time.time() // 60)}"
    cache.add(key, 0, timeout=120)
    try:
        return cache.incr(key) <= TESTS_PER_MINUTE
    except ValueError:  # expired in between
        return False


def test_channel(actor: AnyUser, channel: Channel) -> bool:
    """Send a real message; the answer is one of two fixed sentences, never the service's."""
    user = _require_owner(actor, channel)
    _require_enabled()
    if not _consume_test(user):
        raise ValidationError(_("Too many tests: wait a minute."))
    with translation.override(preferences_of(user).language):
        title = _("HouseCairn test")
        body = _("This channel receives the reminders of your tasks.")
    return outbound.send(channel.url, title=title, body=body)


# ---------- preferences ----------


def preferences_of(user: User) -> Preference:
    """The person's preferences; the defaults, not saved, if they never changed any."""
    found: Preference | None = Preference.objects.filter(user=user).first()
    return found or Preference(user=user, language=_language())


def _language() -> str:
    current = (translation.get_language() or "").split("-")[0]
    codes = {code for code, _name in Preference._meta.get_field("language").choices or ()}
    return current if current in codes else str(Preference._meta.get_field("language").default)


def update_preferences(actor: AnyUser, **changes: Any) -> Preference:
    user = _person(actor)
    unknown = set(changes) - PREFERENCE_FIELDS
    if unknown:
        raise ValueError(f"Cannot change: {', '.join(sorted(unknown))}")
    prefs = preferences_of(user)
    for field, value in changes.items():
        setattr(prefs, field, value)
    errors: dict[str, list[str]] = {}
    if (prefs.quiet_start is None) != (prefs.quiet_end is None):
        errors["quiet_end"] = [_("Give the start and the end of the quiet hours, or neither.")]
    if prefs.time_zone and prefs.time_zone not in _zones():
        errors["time_zone"] = [_("Choose a time zone such as Europe/Paris.")]
    if errors:
        raise ValidationError(errors)
    prefs.full_clean(exclude=["user"])
    prefs.save()
    return prefs


def _zones() -> set[str]:
    return set(zoneinfo.available_timezones()) | {"UTC"}


def export_of(actor: AnyUser) -> dict[str, Any]:
    """What the account keeps for notifications: never the address of a channel."""
    user = _person(actor)
    prefs = preferences_of(user)
    return {
        "channels": [
            {
                "id": str(c.id),
                "name": c.name,
                "scheme": c.scheme,
                "service": c.service,
                "enabled": c.enabled,
                "created_at": c.created_at.isoformat(),
            }
            for c in channels_of(user)
        ],
        "preferences": {
            field: (str(v) if (v := getattr(prefs, field)) is not None else None)
            if field in {"send_at", "quiet_start", "quiet_end"}
            else getattr(prefs, field)
            for field in sorted(PREFERENCE_FIELDS)
        },
    }
