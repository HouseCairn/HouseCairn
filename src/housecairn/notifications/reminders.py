"""Which reminders are due, and sending each one once (docs/adr/0043).

`dispatch` runs in the background worker every few minutes (docs/adr/0008). For each open
occurrence with a due date, the people to remind are the person in charge of the task, or,
when nobody is, every member of the home who may write and has a channel on. A person's
first reminder goes out `days_before` days before the due date, from `send_at` in their
time zone; follow-ups come every `FOLLOW_UP_DAYS[priority]` days while the occurrence stays
open. Postponing moves the due date, so the reminders start again from the new date; done
and skipped close the occurrence, so they stop.

Each message has a key (occurrence, due date, follow-up number; or the day of a summary).
It is claimed by inserting a `Delivery` row before anything is sent: the unique constraint
lets one worker only send it, even when two runs cross. A message claimed and not sent (the
service failed, the worker stopped) is not tried again; the next follow-up is.
"""

import datetime
import logging
import zoneinfo
from collections import defaultdict
from typing import Any

from django.db import IntegrityError, models, transaction
from django.urls import reverse
from django.utils import formats, timezone, translation
from django.utils.translation import gettext as _

from housecairn.accounts.models import User
from housecairn.homes.models import WRITE_ROLES, Membership
from housecairn.instance.config import get_setting, instance_zone
from housecairn.notifications import outbound, services
from housecairn.notifications.models import Channel, Delivery, Kind, Preference
from housecairn.tasks.models import OPEN_STATUSES, Occurrence

logger = logging.getLogger("housecairn.notifications")

FOLLOW_UP_DAYS = {"high": 1, "normal": 3, "low": 7}
MAX_DAYS_BEFORE = 30
KEEP_DELIVERIES_DAYS = 90
DIGEST_LIMIT = 30


def zone_of(prefs: Preference) -> datetime.tzinfo:
    if prefs.time_zone:
        try:
            return zoneinfo.ZoneInfo(prefs.time_zone)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            pass
    return instance_zone()


def is_quiet(prefs: Preference, local: datetime.datetime) -> bool:
    """Within the quiet hours, which may run past midnight (22:00 to 07:00)."""
    start, end = prefs.quiet_start, prefs.quiet_end
    if start is None or end is None or start == end:
        return False
    moment = local.time()
    return start <= moment < end if start < end else (moment >= start or moment < end)


def first_reminder(due_on: datetime.date, prefs: Preference) -> datetime.datetime:
    day = due_on - datetime.timedelta(days=prefs.days_before)
    return datetime.datetime.combine(day, prefs.send_at, tzinfo=zone_of(prefs))


def _link(occurrence: Occurrence) -> str:
    site = str(get_setting("site_url") or "").rstrip("/")
    if not site:
        return ""
    return site + reverse(
        "tasks:detail", kwargs={"home_id": occurrence.home_id, "task_id": occurrence.task_id}
    )


def _line(occurrence: Occurrence) -> str:
    """Title, home, due date and link: nothing else of the task leaves the instance."""
    text = _("%(title)s, %(home)s, due %(date)s") % {
        "title": occurrence.task.title,
        "home": occurrence.home.name,
        "date": formats.date_format(occurrence.due_on, "DATE_FORMAT") if occurrence.due_on else "",
    }
    link = _link(occurrence)
    return f"{text}\n{link}" if link else text


def reminder_message(occurrence: Occurrence, prefs: Preference) -> tuple[str, str]:
    """Plain text: `outbound.send` lets Apprise escape it for each channel. The title of a
    message is fixed, since some services render it as markup of their own."""
    with translation.override(prefs.language):
        return _("HouseCairn reminder"), _line(occurrence)


def digest_message(rows: list[Occurrence], prefs: Preference) -> tuple[str, str]:
    with translation.override(prefs.language):
        lines = [_line(o) for o in rows[:DIGEST_LIMIT]]
        if len(rows) > DIGEST_LIMIT:
            lines.append(_("And %(n)d more.") % {"n": len(rows) - DIGEST_LIMIT})
        return _("HouseCairn: tasks to do"), "\n\n".join(lines)


def _deliver(
    user: User,
    kind: Kind,
    key: str,
    message: tuple[str, str],
    channels: list[Channel],
    occurrence: Occurrence | None = None,
) -> bool:
    """Claim the message, then send it to each channel on. False if already claimed."""
    try:
        with transaction.atomic():
            delivery = Delivery.objects.create(user=user, kind=kind, key=key, occurrence=occurrence)
    except IntegrityError:
        return False
    title, body = message
    results = [outbound.send(c.url, title=title, body=body) for c in channels]
    if any(results):
        Delivery.objects.filter(pk=delivery.pk).update(sent=True)
    return True


def _recipients(
    occurrence: Occurrence, writers: dict[Any, set[Any]], reachable: set[Any]
) -> set[Any]:
    allowed = writers.get(occurrence.home_id, set()) & reachable
    assignee = occurrence.task.assignee_id
    if assignee is not None:
        return {assignee} & allowed
    return allowed


def dispatch(now: datetime.datetime | None = None) -> int:
    """Send what is due; the number of messages claimed. Nothing when notifications are off."""
    if not services.is_enabled():
        return 0
    now = now or timezone.now()
    Delivery.objects.filter(
        claimed_at__lt=now - datetime.timedelta(days=KEEP_DELIVERIES_DAYS)
    ).delete()
    channels: dict[Any, list[Channel]] = defaultdict(list)
    for channel in Channel.objects.filter(enabled=True).select_related("user"):
        if channel.user.is_active:
            channels[channel.user_id].append(channel)
    if not channels:
        return 0
    writers: dict[Any, set[Any]] = defaultdict(set)
    for home_id, user_id in Membership.objects.filter(
        user_id__in=channels, role__in=WRITE_ROLES
    ).values_list("home_id", "user_id"):
        writers[home_id].add(user_id)
    prefs = {p.user_id: p for p in Preference.objects.filter(user_id__in=channels)}
    users = {u.pk: u for u in User.objects.filter(pk__in=channels)}

    def prefs_of(user_id: Any) -> Preference:
        return prefs.get(user_id) or Preference(user=users[user_id])

    horizon = timezone.localdate(now, instance_zone()) + datetime.timedelta(
        days=MAX_DAYS_BEFORE + 1
    )
    rows = (
        Occurrence.objects.filter(
            home_id__in=writers,
            status__in=OPEN_STATUSES,
            due_on__isnull=False,
            due_on__lte=horizon,
            task__deleted_at__isnull=True,
        )
        .select_related("task", "home")
        .order_by(models.F("due_on").asc(), "created_at", "id")
    )
    claimed = 0
    digests: dict[Any, list[Occurrence]] = defaultdict(list)
    for occurrence in rows:
        due_on = occurrence.due_on
        if due_on is None:
            continue
        for user_id in _recipients(occurrence, writers, set(channels)):
            pref = prefs_of(user_id)
            local = now.astimezone(zone_of(pref))
            start = first_reminder(due_on, pref)
            if local < start:
                continue
            if pref.digest:
                digests[user_id].append(occurrence)
                continue
            if is_quiet(pref, local):
                continue  # sent at the first run after the quiet hours
            step = datetime.timedelta(days=FOLLOW_UP_DAYS.get(occurrence.task.priority, 3))
            number = (local - start) // step
            key = f"{occurrence.id}:{due_on.isoformat()}:{number}"
            message = reminder_message(occurrence, pref)
            claimed += _deliver(
                users[user_id], Kind.REMINDER, key, message, channels[user_id], occurrence
            )
    for user_id, found in digests.items():
        pref = prefs_of(user_id)
        local = now.astimezone(zone_of(pref))
        if is_quiet(pref, local):
            continue
        # The summary of a day is due from `send_at` that day until `send_at` the next:
        # quiet hours delay it, they never skip it.
        shift = datetime.timedelta(hours=pref.send_at.hour, minutes=pref.send_at.minute)
        day = (local.replace(tzinfo=None) - shift).date()
        message = digest_message(found, pref)
        claimed += _deliver(
            users[user_id], Kind.DIGEST, day.isoformat(), message, channels[user_id]
        )
    return claimed
