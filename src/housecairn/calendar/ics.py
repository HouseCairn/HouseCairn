"""The iCalendar document of a feed (RFC 5545), written by the `icalendar` library (ADR 0052).

The library escapes commas, semicolons, backslashes and line breaks and folds lines at 75
octets; titles are also reduced to one line of printable characters before they get there.
A task carries here its title, home, room, due date, status and a link, nothing else: no
note, cost, procedure, attachment, person or email address.
"""

import datetime
from typing import Any

from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import pgettext
from icalendar import Calendar, Event

from housecairn.calendar import services
from housecairn.calendar.feeds import feed_homes
from housecairn.calendar.models import Feed
from housecairn.instance.config import instance_name
from housecairn.notifications import services as notification_services
from housecairn.tasks.models import Status

PAST_DAYS = 30
FUTURE_DAYS = 365
REFRESH = datetime.timedelta(hours=6)
_STATUS_ICS = {Status.SKIPPED: "CANCELLED"}


def uid_of(entry: services.Entry) -> str:
    """`<task id>-<date>@housecairn`, for a forecast and for the occurrence that replaces it.

    The date is the one the occurrence was first due on (`postponed_from` when it was
    postponed), so a forecast that becomes an occurrence, and an occurrence that is postponed,
    keep their identity: the calendar application moves or updates the event, it does not
    delete one and create another.
    """
    return f"{entry.task_id}-{entry.identity_day.isoformat()}@housecairn"


def _unique_uid(entry: services.Entry, seen: set[str]) -> str | None:
    """The identity above, unless another event of the document already has it.

    Two occurrences of a task can share a first date (a postponement that lands back on the
    date of the next occurrence): the second one then takes its own id, which is unique. A
    forecast that meets an existing identity is dropped: the recorded occurrence stands.
    """
    uid = uid_of(entry)
    if uid in seen:
        if entry.occurrence_id is None:
            return None
        uid = f"{entry.occurrence_id}@housecairn"
    seen.add(uid)
    return uid


def _event(entry: services.Entry, base_url: str, uid: str) -> Event:
    status = str(Status(entry.status).label)
    home = services.clean_title(entry.home.name)
    summary = entry.title
    if entry.status in (Status.DONE, Status.SKIPPED):
        summary = f"[{status}] {summary}"
    state = status + (" (" + _("forecast") + ")" if entry.projected else "")
    lines = [_("Status") + ": " + state, pgettext("calendar", "Home") + ": " + home]
    if entry.room:
        lines.append(_("Room") + ": " + services.clean_title(entry.room))
    event = Event()
    event.add("uid", uid)
    event.add("dtstamp", entry.updated_at.astimezone(datetime.UTC))
    event.add("dtstart", entry.day)
    event.add("dtend", entry.day + datetime.timedelta(days=1))
    event.add("summary", summary)
    event.add("description", "\n".join(lines))
    event.add("location", home)
    event.add("status", _STATUS_ICS.get(Status(entry.status), "CONFIRMED"))
    event.add("transp", "TRANSPARENT")
    path = reverse("tasks:detail", kwargs={"home_id": entry.home.id, "task_id": entry.task_id})
    event.add("url", f"{base_url}{path}")
    return event


def render(feed: Feed, base_url: str, *, now: datetime.datetime | None = None) -> bytes:
    """The calendar of a feed, in the language and the time zone of its person.

    The body depends on the data only (no clock in it besides the window around today), so
    the same data gives the same bytes, and the same ETag.
    """
    user = feed.user
    zone = services.zone_of(user)
    today = services.today_of(user, now)
    language = notification_services.preferences_of(user).language
    homes: list[Any] = [feed.home] if feed.home else list(feed_homes(user))
    with translation.override(language):
        result = services.entries(
            user,
            homes,
            today - datetime.timedelta(days=PAST_DAYS),
            today + datetime.timedelta(days=FUTURE_DAYS),
        )
        calendar = Calendar()
        calendar.add("prodid", "-//HouseCairn//Calendar//EN")
        calendar.add("version", "2.0")
        calendar.add("calscale", "GREGORIAN")
        calendar.add("method", "PUBLISH")
        name = services.clean_title(feed.home.name) if feed.home else _("All my homes")
        calendar.add("x-wr-calname", f"{instance_name()}: {name}")
        calendar.add("x-wr-timezone", str(zone))
        calendar.add("refresh-interval", REFRESH, parameters={"VALUE": "DURATION"})
        calendar.add("x-published-ttl", REFRESH)
        seen: set[str] = set()
        for entry in result.entries:
            uid = _unique_uid(entry, seen)
            if uid is not None:
                calendar.add_component(_event(entry, base_url, uid))
        return bytes(calendar.to_ical())
