"""Recurrence of tasks, by the RFC 5545 engine of python-dateutil (docs/adr/0031).

Pure functions on calendar dates: no model, no clock, no time zone. A due date
is a day, so a change of clock cannot move it. The month-end rule is the one a
person expects: a task set on the 31st falls on the last day of shorter months,
and a task set on 29 February falls on 28 February in other years.
"""

import datetime
from dataclasses import dataclass
from typing import Any

from dateutil.relativedelta import relativedelta
from dateutil.rrule import DAILY, MONTHLY, WEEKLY, YEARLY, rrule

ONCE = "once"
FIXED = "fixed"
AFTER_LAST = "after_last"
MODES = (ONCE, FIXED, AFTER_LAST)

DAY, WEEK, MONTH, YEAR = "day", "week", "month", "year"
UNITS = (DAY, WEEK, MONTH, YEAR)
_FREQUENCY: dict[str, Any] = {DAY: DAILY, WEEK: WEEKLY, MONTH: MONTHLY, YEAR: YEARLY}
# Largest interval of each unit: about fifty years, so that a date stays far from 9999.
MAX_INTERVAL = {DAY: 18_250, WEEK: 2_600, MONTH: 600, YEAR: 50}


@dataclass(frozen=True)
class Rule:
    """How a task comes back.

    `season_start` and `season_end` are months (1-12) of a window outside of which
    nothing falls; the window may run over the new year (November to March).
    """

    mode: str = ONCE
    unit: str = MONTH
    interval: int = 1
    season_start: int | None = None
    season_end: int | None = None

    @property
    def repeats(self) -> bool:
        return self.mode != ONCE


def problems(rule: Rule) -> list[str]:
    """Why the rule is unusable, as codes; empty when it is fine."""
    found: list[str] = []
    if rule.mode not in MODES:
        found.append("mode")
    elif rule.mode != ONCE:
        if rule.unit not in UNITS:
            found.append("unit")
        elif not 1 <= rule.interval <= MAX_INTERVAL[rule.unit]:
            found.append("interval")
    if (rule.season_start is None) != (rule.season_end is None) or (
        rule.season_start is not None
        and not (1 <= rule.season_start <= 12 and 1 <= (rule.season_end or 0) <= 12)
    ):
        found.append("season")
    return found


def in_season(rule: Rule, day: datetime.date) -> bool:
    if rule.season_start is None or rule.season_end is None:
        return True
    start, end = rule.season_start, rule.season_end
    if start <= end:
        return start <= day.month <= end
    return day.month >= start or day.month <= end


def _enter_season(rule: Rule, day: datetime.date) -> datetime.date:
    """`day`, or the first day of the next season when `day` is out of season."""
    if in_season(rule, day):
        return day
    assert rule.season_start is not None  # noqa: S101 - narrows the type
    year = day.year if day.month < rule.season_start else day.year + 1
    return datetime.date(year, rule.season_start, 1)


def _delta(rule: Rule) -> relativedelta:
    n = rule.interval
    if rule.unit == DAY:
        return relativedelta(days=n)
    if rule.unit == WEEK:
        return relativedelta(weeks=n)
    if rule.unit == MONTH:
        return relativedelta(months=n)
    return relativedelta(years=n)


def _series(rule: Rule, anchor: datetime.date) -> rrule:
    """The dates of a fixed rule, from its first date (the anchor).

    From the 29th of a month, a month is "the 29th, or the last day if earlier":
    the day is a set of two candidates and the first one that exists is kept
    (BYSETPOS=1). The anchor, not the previous date, carries the day: 31 January,
    28 February, 31 March.
    """
    extra: dict[str, object] = {}
    if rule.unit == MONTH and anchor.day > 28:
        extra = {"bymonthday": (anchor.day, -1), "bysetpos": 1}
    elif rule.unit == YEAR and anchor.day > 28:
        extra = {"bymonth": anchor.month, "bymonthday": (anchor.day, -1), "bysetpos": 1}
    return rrule(
        _FREQUENCY[rule.unit],
        interval=rule.interval,
        dtstart=datetime.datetime.combine(anchor, datetime.time()),
        **extra,  # type: ignore[arg-type]
    )


def next_due(
    rule: Rule,
    *,
    anchor: datetime.date | None,
    due_on: datetime.date | None,
    done_on: datetime.date,
) -> datetime.date | None:
    """The due date that follows an occurrence closed on `done_on`; None for a task done once.

    - `after_last`: `done_on` plus the interval.
    - `fixed`: the first date of the series after both the due date and `done_on`:
      dates missed meanwhile are not brought back one by one, the arrears is the
      occurrence not yet closed.

    A date out of season moves to the first day of the next season.
    """
    if not rule.repeats:
        return None
    try:
        if rule.mode == AFTER_LAST:
            candidate = done_on + _delta(rule)
        else:
            after = max(due_on, done_on) if due_on else done_on
            start = min(anchor or after, after)
            found = _series(rule, start).after(
                datetime.datetime.combine(after, datetime.time()), inc=False
            )
            if found is None:  # pragma: no cover - the series is endless
                return None
            candidate = found.date()
        return _enter_season(rule, candidate)
    except (OverflowError, ValueError):
        return None


def preview(
    rule: Rule, *, anchor: datetime.date | None, due_on: datetime.date, count: int
) -> list[datetime.date]:
    """The next `count` due dates, were each occurrence closed on its due date."""
    dates: list[datetime.date] = []
    current: datetime.date | None = due_on
    while current is not None and len(dates) < count:
        current = next_due(rule, anchor=anchor, due_on=current, done_on=current)
        if current is not None:
            dates.append(current)
    return dates
