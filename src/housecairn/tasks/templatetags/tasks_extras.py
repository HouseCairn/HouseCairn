import datetime

from django import template
from django.db.models import F
from django.utils.dates import MONTHS
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from housecairn.accounts.names import person_name
from housecairn.rooms.models import Item, Room
from housecairn.tasks import markup
from housecairn.tasks.models import OPEN_STATUSES, Occurrence, RepeatMode, Season, Task

register = template.Library()


@register.filter
def markdown(value: str) -> SafeString:
    """The procedure of a task as safe HTML (docs/adr/0031)."""
    return markup.render(value)


@register.filter
def late_days(occurrence: Occurrence, today: datetime.date) -> int:
    """How many days an open occurrence is past its date; 0 if it is not."""
    if not occurrence.is_open or occurrence.due_on is None or occurrence.due_on >= today:
        return 0
    return (today - occurrence.due_on).days


@register.filter
def days_until(occurrence: Occurrence, today: datetime.date) -> int | None:
    if occurrence.due_on is None:
        return None
    return (occurrence.due_on - today).days


@register.filter
def repeat_summary(task: Task) -> str:
    """The rule of a task in a sentence, in the language of the interface."""
    n = task.repeat_interval
    unit = task.repeat_unit
    if task.repeat_mode == RepeatMode.ONCE:
        return _("Once")
    if task.repeat_mode == RepeatMode.FIXED:
        text = {
            "day": ngettext("Every day", "Every %(n)d days", n),
            "week": ngettext("Every week", "Every %(n)d weeks", n),
            "month": ngettext("Every month", "Every %(n)d months", n),
            "year": ngettext("Every year", "Every %(n)d years", n),
        }[unit] % {"n": n}
    else:
        text = {
            "day": ngettext("A day after the last time", "%(n)d days after the last time", n),
            "week": ngettext("A week after the last time", "%(n)d weeks after the last time", n),
            "month": ngettext("A month after the last time", "%(n)d months after the last time", n),
            "year": ngettext("A year after the last time", "%(n)d years after the last time", n),
        }[unit] % {"n": n}
    if task.season_start_month and task.season_end_month:
        if task.season and task.season != Season.CUSTOM:
            text += ", " + str(Season(task.season).label)
        text += ", " + _("from %(start)s to %(end)s") % {
            "start": MONTHS[task.season_start_month],
            "end": MONTHS[task.season_end_month],
        }
    return text


@register.simple_tag
def open_occurrences_for(target: Room | Item) -> list[Occurrence]:
    """The open occurrences of the tasks of a room or of an item, oldest date first.

    For the sheets of rooms and items, which only read them (docs/adr/0031).
    """
    field = "task__room" if isinstance(target, Room) else "task__item"
    rows = Occurrence.objects.filter(
        home_id=target.home_id,
        task__deleted_at__isnull=True,
        status__in=OPEN_STATUSES,
        **{field: target},
    ).select_related("task")
    return list(rows.order_by(F("due_on").asc(nulls_last=True), "created_at", "id")[:20])


@register.filter
def where_and_who(occurrence: Occurrence) -> str:
    """Where a closed occurrence happened and who was involved, in one line for History."""
    task = occurrence.task
    parts = [
        task.room.name if task.room else "",
        task.item.name if task.item else "",
        task.contractor.name if task.contractor else "",
        person_name(occurrence.completed_by),
    ]
    return " · ".join(part for part in parts if part)
