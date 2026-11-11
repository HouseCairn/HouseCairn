"""Recurrence of tasks, by the RFC 5545 engine of python-dateutil (docs/adr/0031).

Pure functions on calendar dates: no model, no clock, no time zone. A due date
is a day, so a change of clock cannot move it. The month-end rule is the one a
person expects: a task set on the 31st falls on the last day of shorter months,
and a task set on 29 February falls on 28 February in other years.
"""

import datetime
from collections.abc import Iterator
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


# Predefined seasons, as the months they cover in the northern hemisphere (docs/adr/0045).
# Meteorological seasons by whole months.
SPRING, SUMMER, AUTUMN, WINTER, CUSTOM = ("spring", "summer", "autumn", "winter", "custom")
# The heating season was a predefined season until 2026-11 (docs/adr/0045, change of
# 2026-11-11): it is now custom months, October to April in the north. An archive, a CSV
# file or an API client of before may still send it; `legacy_season` gives its months.
HEATING = "heating"
NORTH, SOUTH = "north", "south"
_NORTH_WINDOWS: dict[str, tuple[int, int]] = {
    SPRING: (3, 5),
    SUMMER: (6, 8),
    AUTUMN: (9, 11),
    WINTER: (12, 2),
}
_LEGACY_WINDOWS: dict[str, tuple[int, int]] = {HEATING: (10, 4)}
PREDEFINED_SEASONS = tuple(_NORTH_WINDOWS)
LEGACY_SEASONS = tuple(_LEGACY_WINDOWS)


def _shift(window: tuple[int, int], hemisphere: str) -> tuple[int, int] | None:
    if hemisphere == NORTH:
        return window
    if hemisphere == SOUTH:
        return ((window[0] + 5) % 12 + 1, (window[1] + 5) % 12 + 1)
    return None


def legacy_season(season: str, hemisphere: str = NORTH) -> tuple[int, int] | None:
    """The months of a season no longer offered (`heating`) in a hemisphere; else None.

    The value is then stored as a custom season with these months: October to April in
    the north, April to October in the south, as the heating season was.
    """
    window = _LEGACY_WINDOWS.get(season)
    return None if window is None else _shift(window, hemisphere)


def season_window(season: str, hemisphere: str = NORTH) -> tuple[int, int] | None:
    """First and last month of a predefined season in a hemisphere; None for any other value.

    The southern hemisphere is the northern one shifted by six months: its summer is
    December to February.
    """
    window = _NORTH_WINDOWS.get(season)
    return None if window is None else _shift(window, hemisphere)


def season_named(start: int | None, end: int | None) -> str:
    """The predefined season (northern hemisphere) that exactly covers these months, or custom."""
    if start is None or end is None:
        return ""
    for season, window in _NORTH_WINDOWS.items():
        if window == (start, end):
            return season
    return CUSTOM


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


def _series(rule: Rule, anchor: datetime.date, start: datetime.date | None = None) -> rrule:
    """The dates of a fixed rule, from its first date (the anchor), counted from `start`.

    `start` is any date of the series (the anchor by default); the day of the month
    always comes from the anchor, which a clamped `start` (the 28th for the 31st) lost.

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
        dtstart=datetime.datetime.combine(start or anchor, datetime.time()),
        **extra,  # type: ignore[arg-type]
    )


def _near(rule: Rule, anchor: datetime.date, after: datetime.date) -> datetime.date:
    """A date of the series of `anchor` shortly before `after`, to count from there.

    A series is the anchor plus a whole number of intervals, so any such date starts
    the same series. One interval is kept before `after` so that no date is skipped.
    Counting from the anchor of a task begun in 1900 would walk a century of days.
    """
    n = rule.interval
    if rule.unit == DAY:
        periods = (after - anchor).days // n
    elif rule.unit == WEEK:
        periods = (after - anchor).days // (7 * n)
    elif rule.unit == MONTH:
        periods = ((after.year - anchor.year) * 12 + after.month - anchor.month) // n
    else:
        periods = (after.year - anchor.year) // n
    steps = max(periods - 1, 0) * n
    delta = {
        DAY: relativedelta(days=steps),
        WEEK: relativedelta(weeks=steps),
        MONTH: relativedelta(months=steps),
        YEAR: relativedelta(years=steps),
    }[rule.unit]
    return anchor + delta


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
            origin = anchor if anchor and anchor < after else after
            start = _near(rule, origin, after)
            found = _series(rule, origin, start).after(
                datetime.datetime.combine(after, datetime.time()), inc=False
            )
            if found is None:  # pragma: no cover - the series is endless
                return None
            candidate = found.date()
        return _enter_season(rule, candidate)
    except (OverflowError, ValueError):
        return None


def _jump(rule: Rule, current: datetime.date, target: datetime.date) -> datetime.date:
    """The last date of the unbroken chain `current`, +1 interval, +2... that is not after `target`.

    Only for a chain with no season: each step adds the same interval, so the dates in
    between need not be visited. A month or a year is only jumped from a day that exists
    in every month (up to the 28th): from the 29th on, a short month clamps the day and
    the chain is walked step by step until it settles.
    """
    n = rule.interval
    if rule.unit in (DAY, WEEK):
        step = n * (7 if rule.unit == WEEK else 1)
        return current + datetime.timedelta(days=((target - current).days // step) * step)
    delta = _delta(rule)
    while current.day > 28 and current + delta <= target:
        current += delta
    if current > target or current.day > 28:
        return current
    gap = (target.year - current.year) * 12 + target.month - current.month
    unit = 12 if rule.unit == YEAR else 1
    steps = max(gap // (unit * n) - 1, 0) * n
    jumped = current + (
        relativedelta(years=steps) if rule.unit == YEAR else relativedelta(months=steps)
    )
    return jumped if jumped <= target else current


def _dates_after(rule: Rule, anchor: datetime.date, last: datetime.date) -> Iterator[datetime.date]:
    """The dates of the fixed series of `anchor`, from the first one after `last`."""
    if rule.unit in (DAY, WEEK):  # a whole number of days apart: no need of the rrule engine
        days = rule.interval * (7 if rule.unit == WEEK else 1)
        day = anchor + datetime.timedelta(days=((last - anchor).days // days + 1) * days)
        gap = datetime.timedelta(days=days)
        while True:
            yield day
            day += gap
    for stamp in _series(rule, anchor, _near(rule, anchor, last)):
        if stamp.date() > last:
            yield stamp.date()


def coming(
    rule: Rule,
    *,
    anchor: datetime.date | None,
    after: datetime.date,
    since: datetime.date,
    end: datetime.date,
) -> list[datetime.date]:
    """The due dates from `since` to `end` that follow an occurrence due on `after`.

    The dates `next_due` would bring one after the other, were each occurrence closed on
    its due date (what the calendar shows), but only those in the range are worked out:
    the dates before `since` are skipped, not visited, however far `since` is. The cost
    follows the range (one year: about 365 dates at most), never the distance from `after`.
    """
    if not rule.repeats or after >= end:
        return []
    found: list[datetime.date] = []
    try:
        if rule.mode == FIXED and anchor and anchor < after:
            # One series for the whole walk: a date of the series is the anchor plus a whole
            # number of intervals, so the walk may start anywhere shortly before the range.
            # A season moves a date out of it to the start of the next season, less than a year
            # on: so with a season the walk starts a year earlier, to catch such a date.
            back = 366 if rule.season_start is not None else 1
            last = max(after, since - datetime.timedelta(days=back))
            for day in _dates_after(rule, anchor, last):
                day = _enter_season(rule, day)
                if day > end:
                    break
                if day > last:
                    last = day
                    if day >= since:
                        found.append(day)
            return found
        # A chain: each date is the one before plus the interval (`after_last`, or a series
        # not begun yet: `next_due` counts from the anchor only once it is behind).
        current = after
        reach = since - datetime.timedelta(days=1)
        if rule.mode == FIXED and anchor:
            reach = min(reach, anchor)
        if rule.season_start is None and reach > after:
            current = _jump(rule, after, reach)
        step = (
            datetime.timedelta(days=rule.interval * (7 if rule.unit == WEEK else 1))
            if rule.unit in (DAY, WEEK)
            else _delta(rule)
        )
        while True:
            current = current + step
            if rule.season_start is not None:
                current = _enter_season(rule, current)
            if current > end:
                break
            if current >= since:
                found.append(current)
            if rule.mode == FIXED and anchor and current > anchor:
                return found + coming(rule, anchor=anchor, after=current, since=since, end=end)
    except (OverflowError, ValueError):
        pass
    return found


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
