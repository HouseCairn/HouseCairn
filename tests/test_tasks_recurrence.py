"""Recurrence of tasks: month ends, leap days, seasons, clock changes (docs/adr/0031, 0032)."""

import datetime
import itertools
import time
import zoneinfo
from unittest import mock

import pytest
from django.utils import timezone
from hypothesis import given
from hypothesis import strategies as st

from housecairn.tasks import recurrence, services
from housecairn.tasks.recurrence import AFTER_LAST, DAY, FIXED, MONTH, ONCE, WEEK, YEAR, Rule

D = datetime.date


def dates(rule: Rule, first: D, count: int = 6) -> list[D]:
    return recurrence.preview(rule, anchor=first, due_on=first, count=count)


class TestFixedDates:
    def test_a_task_done_once_has_no_next_date(self) -> None:
        assert (
            recurrence.next_due(
                Rule(ONCE), anchor=D(2026, 1, 1), due_on=D(2026, 1, 1), done_on=D(2026, 1, 1)
            )
            is None
        )

    def test_every_day_week_month_and_year(self) -> None:
        first = D(2026, 3, 10)
        assert dates(Rule(FIXED, DAY, 3), first, 3) == [
            D(2026, 3, 13),
            D(2026, 3, 16),
            D(2026, 3, 19),
        ]
        assert dates(Rule(FIXED, WEEK, 2), first, 2) == [D(2026, 3, 24), D(2026, 4, 7)]
        assert dates(Rule(FIXED, MONTH, 1), first, 2) == [D(2026, 4, 10), D(2026, 5, 10)]
        assert dates(Rule(FIXED, YEAR, 1), first, 2) == [D(2027, 3, 10), D(2028, 3, 10)]

    def test_the_end_of_the_month_follows_the_anchor_not_the_previous_date(self) -> None:
        assert dates(Rule(FIXED, MONTH, 1), D(2026, 1, 31), 5) == [
            D(2026, 2, 28),
            D(2026, 3, 31),
            D(2026, 4, 30),
            D(2026, 5, 31),
            D(2026, 6, 30),
        ]

    def test_the_30th_in_february(self) -> None:
        assert dates(Rule(FIXED, MONTH, 1), D(2028, 1, 30), 2) == [D(2028, 2, 29), D(2028, 3, 30)]

    def test_the_29th_of_february_falls_on_the_28th_in_other_years(self) -> None:
        assert dates(Rule(FIXED, YEAR, 1), D(2024, 2, 29), 5) == [
            D(2025, 2, 28),
            D(2026, 2, 28),
            D(2027, 2, 28),
            D(2028, 2, 29),
            D(2029, 2, 28),
        ]

    def test_every_four_years_keeps_the_leap_day(self) -> None:
        assert dates(Rule(FIXED, YEAR, 4), D(2024, 2, 29), 2) == [D(2028, 2, 29), D(2032, 2, 29)]

    def test_arrears_are_not_brought_back_one_by_one(self) -> None:
        """Done long after: the next date is the first one after today, not the next missed one."""
        rule = Rule(FIXED, MONTH, 1)
        assert recurrence.next_due(
            rule, anchor=D(2026, 1, 15), due_on=D(2026, 1, 15), done_on=D(2026, 5, 20)
        ) == D(2026, 6, 15)

    def test_done_early_does_not_pull_the_next_date_forward(self) -> None:
        rule = Rule(FIXED, MONTH, 1)
        assert recurrence.next_due(
            rule, anchor=D(2026, 3, 15), due_on=D(2026, 3, 15), done_on=D(2026, 3, 1)
        ) == D(2026, 4, 15)

    def test_without_anchor_the_series_starts_from_the_completion(self) -> None:
        assert recurrence.next_due(
            Rule(FIXED, WEEK, 1), anchor=None, due_on=None, done_on=D(2026, 3, 10)
        ) == D(2026, 3, 17)

    def test_a_date_beyond_the_calendar_ends_the_series(self) -> None:
        assert (
            recurrence.next_due(
                Rule(AFTER_LAST, YEAR, 50), anchor=None, due_on=None, done_on=D(9990, 1, 1)
            )
            is None
        )
        assert (
            recurrence.next_due(
                Rule(FIXED, YEAR, 50),
                anchor=D(9990, 1, 1),
                due_on=D(9990, 1, 1),
                done_on=D(9990, 1, 1),
            )
            is None
        )


class TestAfterTheLastTime:
    def test_the_next_date_starts_from_the_day_it_was_done(self) -> None:
        rule = Rule(AFTER_LAST, MONTH, 6)
        assert recurrence.next_due(
            rule, anchor=None, due_on=D(2026, 1, 1), done_on=D(2026, 2, 10)
        ) == D(2026, 8, 10)

    def test_month_end_and_leap_day(self) -> None:
        month = Rule(AFTER_LAST, MONTH, 1)
        assert recurrence.next_due(month, anchor=None, due_on=None, done_on=D(2026, 1, 31)) == D(
            2026, 2, 28
        )
        year = Rule(AFTER_LAST, YEAR, 1)
        assert recurrence.next_due(year, anchor=None, due_on=None, done_on=D(2024, 2, 29)) == D(
            2025, 2, 28
        )

    def test_every_unit(self) -> None:
        done = D(2026, 3, 10)
        for unit, expected in (
            (DAY, D(2026, 3, 12)),
            (WEEK, D(2026, 3, 24)),
            (MONTH, D(2026, 5, 10)),
            (YEAR, D(2028, 3, 10)),
        ):
            rule = Rule(AFTER_LAST, unit, 2)
            assert recurrence.next_due(rule, anchor=None, due_on=None, done_on=done) == expected


class TestSeasons:
    def test_outside_the_season_the_date_waits_for_its_first_day(self) -> None:
        rule = Rule(FIXED, WEEK, 1, season_start=4, season_end=10)
        assert recurrence.next_due(
            rule, anchor=D(2026, 10, 26), due_on=D(2026, 10, 26), done_on=D(2026, 10, 26)
        ) == D(2027, 4, 1)

    def test_before_the_season_of_the_same_year(self) -> None:
        rule = Rule(AFTER_LAST, MONTH, 1, season_start=4, season_end=10)
        assert recurrence.next_due(rule, anchor=None, due_on=None, done_on=D(2026, 1, 20)) == D(
            2026, 4, 1
        )

    def test_a_season_over_the_new_year(self) -> None:
        rule = Rule(AFTER_LAST, DAY, 30, season_start=11, season_end=3)
        assert recurrence.in_season(rule, D(2026, 12, 25))
        assert recurrence.in_season(rule, D(2027, 2, 1))
        assert not recurrence.in_season(rule, D(2026, 7, 1))
        assert recurrence.next_due(rule, anchor=None, due_on=None, done_on=D(2027, 3, 10)) == D(
            2027, 11, 1
        )
        assert recurrence.next_due(rule, anchor=None, due_on=None, done_on=D(2026, 11, 5)) == D(
            2026, 12, 5
        )

    def test_a_date_inside_the_season_is_left_alone(self) -> None:
        rule = Rule(AFTER_LAST, DAY, 7, season_start=4, season_end=10)
        assert recurrence.next_due(rule, anchor=None, due_on=None, done_on=D(2026, 6, 1)) == D(
            2026, 6, 8
        )


class TestValidation:
    def test_a_good_rule_has_no_problem(self) -> None:
        assert recurrence.problems(Rule(FIXED, MONTH, 3, 4, 10)) == []
        assert recurrence.problems(Rule(ONCE)) == []

    @pytest.mark.parametrize(
        ("rule", "code"),
        [
            (Rule("sometimes"), "mode"),
            (Rule(FIXED, "decade", 1), "unit"),
            (Rule(FIXED, MONTH, 0), "interval"),
            (Rule(FIXED, YEAR, 51), "interval"),
            (Rule(FIXED, MONTH, 1, 4, None), "season"),
            (Rule(FIXED, MONTH, 1, 13, 2), "season"),
        ],
    )
    def test_problems_are_named(self, rule: Rule, code: str) -> None:
        assert code in recurrence.problems(rule)


class TestClockChanges:
    """A due date is a day: neither a change of clock nor a time zone can move it (ADR 0032)."""

    def test_a_daily_series_has_one_date_per_day_across_a_change_of_clock(self) -> None:
        # In France the clocks went forward on 29 March 2026 and back on 25 October 2026.
        for start in (D(2026, 3, 27), D(2026, 10, 23)):
            series = [start, *dates(Rule(FIXED, DAY, 1), start, 5)]
            assert [(b - a).days for a, b in itertools.pairwise(series)] == [1] * 5

    def test_a_weekly_series_keeps_its_weekday(self) -> None:
        series = dates(Rule(FIXED, WEEK, 1), D(2026, 3, 23), 4)
        assert {day.weekday() for day in series} == {D(2026, 3, 23).weekday()}

    def test_today_follows_the_zone_of_the_instance(self) -> None:
        moment = datetime.datetime(2026, 3, 28, 23, 30, tzinfo=datetime.UTC)
        with mock.patch("django.utils.timezone.now", return_value=moment):
            with timezone.override(zoneinfo.ZoneInfo("UTC")):
                assert services.today() == D(2026, 3, 28)
            with timezone.override(zoneinfo.ZoneInfo("Europe/Paris")):
                assert services.today() == D(2026, 3, 29)

    def test_a_day_is_a_day_on_the_night_the_clocks_change(self) -> None:
        """23 hours or 25 hours of elapsed time, still one calendar day (ADR 0032)."""
        paris = zoneinfo.ZoneInfo("Europe/Paris")
        spring = (
            datetime.datetime(2026, 3, 30, tzinfo=paris),
            datetime.datetime(2026, 3, 29, tzinfo=paris),
        )
        assert (
            spring[0].astimezone(datetime.UTC) - spring[1].astimezone(datetime.UTC)
        ).total_seconds() == 23 * 3600
        assert (spring[0].date() - spring[1].date()).days == 1
        autumn = (
            datetime.datetime(2026, 10, 26, tzinfo=paris),
            datetime.datetime(2026, 10, 25, tzinfo=paris),
        )
        assert (
            autumn[0].astimezone(datetime.UTC) - autumn[1].astimezone(datetime.UTC)
        ).total_seconds() == 25 * 3600
        assert (
            recurrence.next_due(
                Rule(AFTER_LAST, DAY, 1), anchor=None, due_on=None, done_on=autumn[1].date()
            )
            == autumn[0].date()
        )


rules = st.builds(
    Rule,
    mode=st.sampled_from([FIXED, AFTER_LAST]),
    unit=st.sampled_from([DAY, WEEK, MONTH, YEAR]),
    interval=st.integers(min_value=1, max_value=30),
    season_start=st.none() | st.integers(min_value=1, max_value=12),
    season_end=st.none() | st.integers(min_value=1, max_value=12),
).filter(lambda rule: (rule.season_start is None) == (rule.season_end is None))
firsts = st.dates(min_value=D(2000, 1, 1), max_value=D(2100, 12, 31))


@given(rule=rules, first=firsts)
def test_generated_dates_always_move_forward_and_stay_in_season(rule: Rule, first: D) -> None:
    """Whatever the rule and the start, each date is after the previous one and in the season."""
    series = dates(rule, first, 12)
    assert len(series) == 12
    previous = first
    for day in series:
        assert day > previous
        assert recurrence.in_season(rule, day)
        previous = day


@given(first=firsts, interval=st.integers(min_value=1, max_value=24))
def test_a_monthly_date_is_the_anchor_day_or_the_last_day_of_the_month(
    first: D, interval: int
) -> None:
    """The day of the month is the anchor's, or the month's last day when it is shorter."""
    rule = Rule(FIXED, MONTH, interval)
    for day in dates(rule, first, 8):
        last = (
            D(day.year + (day.month == 12), day.month % 12 + 1, 1) - datetime.timedelta(days=1)
        ).day
        assert day.day == min(first.day, last)


@given(first=firsts, done_after=st.integers(min_value=0, max_value=800))
def test_the_next_fixed_date_is_after_both_the_due_date_and_the_completion(
    first: D, done_after: int
) -> None:
    """Closing late never creates an occurrence in the past of the closing."""
    rule = Rule(FIXED, WEEK, 1)
    done = first + datetime.timedelta(days=done_after)
    following = recurrence.next_due(rule, anchor=first, due_on=first, done_on=done)
    assert following is not None
    assert following > done
    assert following > first
    assert (following - first).days % 7 == 0


@given(rule=rules, done=firsts)
def test_after_the_last_time_is_never_before_the_completion(rule: Rule, done: D) -> None:
    following = recurrence.next_due(
        Rule(AFTER_LAST, rule.unit, rule.interval, rule.season_start, rule.season_end),
        anchor=None,
        due_on=None,
        done_on=done,
    )
    assert following is not None
    assert following > done


@given(
    rule=rules.filter(lambda rule: rule.mode == FIXED),
    first=firsts,
    gap=st.integers(min_value=0, max_value=5000),
)
def test_counting_from_near_the_reference_gives_the_dates_of_the_series_itself(
    rule: Rule, first: D, gap: int
) -> None:
    """Starting the count close to the reference changes nothing: same date as from the anchor."""
    after = first + datetime.timedelta(days=gap)
    quick = recurrence.next_due(rule, anchor=first, due_on=after, done_on=after)
    full = recurrence._series(rule, first).after(
        datetime.datetime.combine(after, datetime.time()), inc=False
    )
    assert quick == recurrence._enter_season(rule, full.date())  # type: ignore[union-attr]


def test_a_series_begun_a_century_ago_is_counted_from_its_recent_past() -> None:
    """A daily task anchored on the oldest allowed date answers at once (docs/adr/0031)."""
    started = D(1926, 6, 15)
    rule = Rule(FIXED, DAY, 1)
    began = time.perf_counter()
    following = recurrence.next_due(
        rule, anchor=started, due_on=D(2026, 6, 15), done_on=D(2026, 6, 15)
    )
    assert following == D(2026, 6, 16)
    assert time.perf_counter() - began < 0.2


def test_even_a_series_begun_in_year_one_is_counted_at_once() -> None:
    """The cost depends on the interval and the reference, not on the age of the anchor."""
    rule = Rule(FIXED, DAY, 1)
    began = time.perf_counter()
    following = recurrence.next_due(
        rule, anchor=D(1, 1, 1), due_on=D(2026, 6, 15), done_on=D(2026, 6, 15)
    )
    assert following == D(2026, 6, 16)
    assert time.perf_counter() - began < 0.2
