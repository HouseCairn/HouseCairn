"""The repetition of a task in one sentence, as the task form shows it under its fields.

Pure text from the values of the form: the words are translated when the sentence is
made, in the language of the request, never when the module is loaded. The dates follow
the format of that language. The month-end rule of `recurrence` is said in words: a task
set on the 31st falls on the last day of shorter months, one set on 29 February on
28 February in other years.
"""

import datetime

from django.utils import formats
from django.utils.dates import MONTHS
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from housecairn.core import dates
from housecairn.tasks import recurrence


def _short(day: datetime.date) -> str:
    return dates.day(day)


def _month_day(day: datetime.date) -> str:
    return dates.month_day(day)


def _after_last(unit: str, n: int) -> str:
    if unit == recurrence.DAY:
        text = ngettext(
            "Next time: %(n)s day after the last time.",
            "Next time: %(n)s days after the last time.",
            n,
        )
    elif unit == recurrence.WEEK:
        text = ngettext(
            "Next time: %(n)s week after the last time.",
            "Next time: %(n)s weeks after the last time.",
            n,
        )
    elif unit == recurrence.MONTH:
        text = ngettext(
            "Next time: %(n)s month after the last time.",
            "Next time: %(n)s months after the last time.",
            n,
        )
    else:
        text = ngettext(
            "Next time: %(n)s year after the last time.",
            "Next time: %(n)s years after the last time.",
            n,
        )
    return text % {"n": n}


def _monthly(n: int, start: datetime.date) -> str:
    values = {"day": start.day, "n": n, "date": _short(start)}
    if n == 1:
        text = _("Day %(day)s of every month, from %(date)s.")
    elif n == 3:
        text = _("Day %(day)s of every quarter, from %(date)s.")
    else:
        text = _("Day %(day)s, every %(n)s months, from %(date)s.")
    text = text % values
    if start.day > 28:
        text += " " + _("In a shorter month, its last day.")
    return text


def _fixed(unit: str, n: int, start: datetime.date) -> str:
    if unit == recurrence.DAY:
        text = ngettext("Every day, from %(date)s.", "Every %(n)s days, from %(date)s.", n) % {
            "n": n,
            "date": _short(start),
        }
    elif unit == recurrence.WEEK:
        weekday = formats.date_format(start, "l")
        text = ngettext(
            "Every %(weekday)s, from %(date)s.",
            "Every %(n)s weeks on %(weekday)s, from %(date)s.",
            n,
        ) % {"n": n, "weekday": weekday, "date": _short(start)}
    elif unit == recurrence.MONTH:
        text = _monthly(n, start)
    else:
        text = ngettext(
            "Every year on %(day)s, from %(date)s.",
            "Every %(n)s years on %(day)s, from %(date)s.",
            n,
        ) % {"n": n, "day": _month_day(start), "date": _short(start)}
        if start.month == 2 and start.day == 29:
            text += " " + _("In other years, 28 February.")
    return text


def _season(window: tuple[int, int] | None) -> str:
    if window is None:
        return ""
    start, end = window
    return _(
        "Only from %(start)s to %(end)s: a date outside moves to the first day of %(start)s."
    ) % {"start": MONTHS[start], "end": MONTHS[end]}


def summary(
    *,
    mode: str,
    unit: str,
    interval: int | None,
    start: datetime.date | None,
    season: tuple[int, int] | None = None,
) -> str:
    """The sentence under the fields: when the task comes back, and in which months."""
    if mode not in (recurrence.FIXED, recurrence.AFTER_LAST):
        return _("Not repeated: the task is done once.")
    if unit not in recurrence.UNITS or not interval or interval < 1:
        return _("Give how often the task comes back.")
    if interval > recurrence.MAX_INTERVAL[unit]:
        return _("This interval is out of range.")
    if mode == recurrence.AFTER_LAST:
        text = _after_last(unit, interval)
    elif start is None:
        text = _("Give the date to count from.")
    else:
        text = _fixed(unit, interval, start)
    extra = _season(season)
    return f"{text} {extra}" if extra else text
