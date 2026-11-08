"""Estimated durations: a number and a unit on screen, minutes in the data (docs/adr/0045)."""

from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

MINUTE, HOUR, DAY = "minute", "hour", "day"
# Minutes in one unit. A day is twenty-four hours: the estimate is of elapsed time.
FACTOR = {MINUTE: 1, HOUR: 60, DAY: 24 * 60}
UNIT_CHOICES = [(MINUTE, _("minutes")), (HOUR, _("hours")), (DAY, _("days"))]
# Business bounds: at least a minute, at most thirty days.
MIN_MINUTES = 1
MAX_MINUTES = 30 * FACTOR[DAY]


def to_minutes(value: int, unit: str) -> int:
    """`value` units as minutes; the caller checks the bounds with `within_bounds`."""
    return value * FACTOR[unit]


def within_bounds(minutes: int) -> bool:
    return MIN_MINUTES <= minutes <= MAX_MINUTES


def split(minutes: int) -> tuple[int, str]:
    """The biggest unit that holds the duration exactly, for a form to show it back."""
    for unit in (DAY, HOUR):
        if minutes % FACTOR[unit] == 0:
            return minutes // FACTOR[unit], unit
    return minutes, MINUTE


def _hours_and_minutes(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"


def label(minutes: int) -> str:
    """A duration people read at a glance: "45 min", "1 h 30", "2 days", "1 day 3 h"."""
    days, rest = divmod(minutes, FACTOR[DAY])
    if days == 0:
        if minutes < 60:
            return ngettext("%(n)d min", "%(n)d min", minutes) % {"n": minutes}
        return _hours_and_minutes(minutes)
    text = ngettext("%(n)d day", "%(n)d days", days) % {"n": days}
    if rest:
        text += " " + (
            _hours_and_minutes(rest)
            if rest >= 60
            else ngettext("%(n)d min", "%(n)d min", rest) % {"n": rest}
        )
    return text
