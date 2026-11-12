"""The nightly reset of a demonstration instance, by the task worker (docs/adr/0008, 0071).

No system cron: a schedule of django-q2, created after `migrate` when `HOUSECAIRN_DEMO` is
true and removed when it is not. Its next run is set again by each run to the next 03:00 in
Paris, so that it follows the changes of summer time.
"""

import datetime
import zoneinfo

from django.db import DatabaseError
from django.utils import timezone

from housecairn.demo import mode, reset

SCHEDULE = "housecairn.demo.nightly_reset"


def next_reset(now: datetime.datetime | None = None) -> datetime.datetime:
    """The next 03:00 in Paris after `now`, as an aware date and time."""
    zone = zoneinfo.ZoneInfo(mode.RESET_TIME_ZONE)
    local = (now or timezone.now()).astimezone(zone)
    candidate = datetime.datetime.combine(local.date(), datetime.time(mode.RESET_HOUR), tzinfo=zone)
    if candidate <= local:
        candidate = datetime.datetime.combine(
            local.date() + datetime.timedelta(days=1), datetime.time(mode.RESET_HOUR), tzinfo=zone
        )
    return candidate


def nightly_reset() -> None:
    """Run by the schedule: the reset, then the date of the next one."""
    if mode.is_on():
        reset.reset()
    schedule()


def schedule(**_kwargs: object) -> None:
    """Create, move or remove the schedule of the reset; called after `migrate`."""
    from django_q.models import Schedule

    try:
        if not mode.is_on():
            Schedule.objects.filter(name=SCHEDULE).delete()
            return
        Schedule.objects.update_or_create(
            name=SCHEDULE,
            defaults={
                "func": "housecairn.demo.tasks.nightly_reset",
                "schedule_type": Schedule.DAILY,
                "repeats": -1,
                "next_run": next_reset(),
            },
        )
    except DatabaseError:  # before django_q's tables exist
        return
