"""Estimated durations: a number and a unit on screen, minutes in the data (docs/adr/0045)."""

from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

MINUTE, HOUR, DAY, WEEK, MONTH, YEAR = "minute", "hour", "day", "week", "month", "year"
# Minutes in one unit. The estimate is of elapsed time: a day is twenty-four hours, a week
# seven days, a month thirty days and a year 365 days, whatever the calendar.
FACTOR = {
    MINUTE: 1,
    HOUR: 60,
    DAY: 24 * 60,
    WEEK: 7 * 24 * 60,
    MONTH: 30 * 24 * 60,
    YEAR: 365 * 24 * 60,
}
UNIT_CHOICES = [
    (MINUTE, _("minutes")),
    (HOUR, _("hours")),
    (DAY, _("days")),
    (WEEK, _("weeks")),
    (MONTH, _("months")),
    (YEAR, _("years")),
]
# Business bounds: at least a minute, at most a year. The one place the ceiling is set:
# the forms, the API and the service read it from here.
MIN_MINUTES = 1
MAX_MINUTES = FACTOR[YEAR]
# From the biggest unit down, for showing a duration back.
_BIG_UNITS = (YEAR, MONTH, WEEK, DAY)


def to_minutes(value: int, unit: str) -> int:
    """`value` units as minutes; the caller checks the bounds with `within_bounds`."""
    return value * FACTOR[unit]


def within_bounds(minutes: int) -> bool:
    return MIN_MINUTES <= minutes <= MAX_MINUTES


def bounds_message() -> str:
    """The error of a duration out of bounds, with the bounds as the page shows them."""
    return _("Give a duration between %(low)s and %(high)s.") % {
        "low": label(MIN_MINUTES),
        "high": label(MAX_MINUTES),
    }


def split(minutes: int) -> tuple[int, str]:
    """The biggest unit that holds the duration exactly, for a form to show it back."""
    for unit in (*_BIG_UNITS, HOUR):
        if minutes % FACTOR[unit] == 0:
            return minutes // FACTOR[unit], unit
    return minutes, MINUTE


def _hours_and_minutes(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"


def _big(count: int, unit: str) -> str:
    if unit == YEAR:
        return ngettext("%(n)d year", "%(n)d years", count) % {"n": count}
    if unit == MONTH:
        return ngettext("%(n)d month", "%(n)d months", count) % {"n": count}
    if unit == WEEK:
        return ngettext("%(n)d week", "%(n)d weeks", count) % {"n": count}
    return ngettext("%(n)d day", "%(n)d days", count) % {"n": count}


def _small(minutes: int) -> str:
    if minutes < 60:
        return ngettext("%(n)d min", "%(n)d min", minutes) % {"n": minutes}
    return _hours_and_minutes(minutes)


def label(minutes: int) -> str:
    """A duration people read at a glance, in the units of the form, biggest first.

    "45 min", "1 h 30", "2 days", "1 day 3 h", "2 weeks", "1 month 1 week", "1 year". A unit
    is a whole number of the smaller ones (a month is thirty days), so nothing is lost.
    """
    parts = []
    rest = minutes
    for unit in _BIG_UNITS:
        count, rest = divmod(rest, FACTOR[unit])
        if count:
            parts.append(_big(count, unit))
    if rest or not parts:
        parts.append(_small(rest))
    return " ".join(parts)
