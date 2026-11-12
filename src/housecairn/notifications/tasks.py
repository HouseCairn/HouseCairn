"""Background task of notifications, run by the worker of the container (docs/adr/0008, 0043)."""

from django.db import DatabaseError

from housecairn.instance.config import get_setting
from housecairn.notifications import reminders

SCHEDULE = "housecairn.notifications.dispatch"


def send_test(channel_id: str, language: str) -> None:
    """Send the test message of a channel (queued by `services.start_test`, docs/adr/0069)."""
    from housecairn.notifications import services

    services.send_test(channel_id, language)


def dispatch() -> int:
    """Send the reminders that are due, then follow the interval of the settings."""
    claimed = reminders.dispatch()
    schedule()
    return claimed


def schedule(**_kwargs: object) -> None:
    """Create or update the schedule of `dispatch`: every `notifications_interval` minutes.

    Called after `migrate` and by each run, so that a change of the interval in the
    interface applies from the next run, without a restart.
    """
    from django_q.models import Schedule

    minutes = int(get_setting("notifications_interval"))
    try:
        found = Schedule.objects.filter(name=SCHEDULE).first()
        if found is None:
            Schedule.objects.create(
                name=SCHEDULE,
                func="housecairn.notifications.tasks.dispatch",
                schedule_type=Schedule.MINUTES,
                minutes=minutes,
                repeats=-1,
            )
        elif found.minutes != minutes or found.schedule_type != Schedule.MINUTES:
            Schedule.objects.filter(pk=found.pk).update(
                minutes=minutes, schedule_type=Schedule.MINUTES, repeats=-1
            )
    except DatabaseError:  # before django_q's tables exist
        return
