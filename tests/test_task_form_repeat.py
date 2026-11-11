"""The repetition of the task form in one sentence (docs/screens/task-form.md).

"Repeat every 3 months, counting from the due date or the day it is done", a summary in
plain words, the fields a choice does not use hidden by script and ignored by the server.
"""

import datetime
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import translation

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.tasks import repeat_text, services
from housecairn.tasks.forms import TaskForm, repeat_summary
from housecairn.tasks.models import Task

pytest_plugins = ("tests.tasks_fixtures", "tests.rooms_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

D = datetime.date
BASE = {
    "title": "Change the filter",
    "priority": "normal",
    "hide_days_before": "0",
    "repeat_unit": "month",
}
REPEATS = {"once": {}, "fixed": {"repeats": "on", "repeat_from": "fixed"}}
REPEATS["after_last"] = {"repeats": "on", "repeat_from": "after_last"}
# (posted, then the season, start and end months stored) for a home of the north.
SEASONS: dict[str, tuple[dict[str, str], tuple[str, int | None, int | None]]] = {
    "all year": ({}, ("", None, None)),
    "spring": ({"season": "spring"}, ("spring", 3, 5)),
    "custom": (
        {"season": "custom", "season_start_month": "10", "season_end_month": "4"},
        ("custom", 10, 4),
    ),
    # Months left in fields hidden by script: ignored for a predefined season.
    "summer, months left": (
        {"season": "summer", "season_start_month": "1", "season_end_month": "2"},
        ("summer", 6, 8),
    ),
}


def create_url(home: Home) -> str:
    return reverse("tasks:create", kwargs={"home_id": home.id})


def edit_url(task: Task) -> str:
    return reverse("tasks:edit", kwargs={"home_id": task.home_id, "task_id": task.id})


def summary_url(home: Home) -> str:
    return reverse("tasks:repeat-summary", kwargs={"home_id": home.id})


class TestEveryCombination:
    @pytest.mark.parametrize("season", list(SEASONS))
    @pytest.mark.parametrize("mode", ["once", "fixed", "after_last"])
    def test_the_sentence_gives_the_mode_and_the_season(
        self, signed_in: Client, alice_home: Home, mode: str, season: str
    ) -> None:
        posted, stored = SEASONS[season]
        data = {
            **BASE,
            **REPEATS[mode],
            "repeat_interval": "3",
            "repeat_unit": "month",
            "due_on": "2027-01-15",
            "repeat_start": "2027-01-15",
            **posted,
        }
        response = signed_in.post(create_url(alice_home), data)
        assert response.status_code == 302, response.text[:2000]
        task = Task.objects.get()
        assert task.repeat_mode == mode
        assert (task.season, task.season_start_month, task.season_end_month) == stored
        assert services.open_occurrence_of(task).due_on == D(2027, 1, 15)  # type: ignore[union-attr]
        if mode != "once":
            assert (task.repeat_interval, task.repeat_unit) == (3, "month")


class TestServerRules:
    def test_unticked_the_task_is_once_whatever_the_hidden_fields_hold(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        data = {**BASE, "repeat_from": "fixed", "repeat_interval": "", "repeat_unit": "week"}
        assert signed_in.post(create_url(alice_home), data).status_code == 302
        task = Task.objects.get()
        assert task.repeat_mode == "once"
        assert task.repeat_interval == 1

    def test_ticked_it_needs_how_often(self, signed_in: Client, alice_home: Home) -> None:
        data = {**BASE, **REPEATS["after_last"], "repeat_interval": "", "repeat_unit": "week"}
        response = signed_in.post(create_url(alice_home), data)
        assert response.status_code == 200
        assert "Give how often the task comes back." in response.text
        assert not Task.objects.exists()

    def test_after_the_last_time_ignores_the_date_of_the_fixed_choice(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        data = {
            **BASE,
            **REPEATS["after_last"],
            "repeat_interval": "2",
            "repeat_unit": "week",
            "repeat_start": "2027-05-01",
        }
        assert signed_in.post(create_url(alice_home), data).status_code == 302
        task = Task.objects.get()
        assert services.open_occurrence_of(task).due_on is None  # type: ignore[union-attr]

    def test_the_date_of_the_fixed_choice_alone_gives_the_due_date(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        data = {
            **BASE,
            **REPEATS["fixed"],
            "repeat_interval": "1",
            "repeat_unit": "year",
            "repeat_start": "2027-03-01",
        }
        assert signed_in.post(create_url(alice_home), data).status_code == 302
        task = Task.objects.get()
        assert services.open_occurrence_of(task).due_on == D(2027, 3, 1)  # type: ignore[union-attr]
        assert task.series_start == D(2027, 3, 1)

    def test_without_script_the_date_changed_wins(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        task = services.create_task(
            alice, alice_home, title="Sweep", repeat_mode="fixed", due_on=D(2026, 7, 1)
        )
        fixed = {**BASE, **REPEATS["fixed"], "repeat_interval": "1", "repeat_unit": "month"}
        # Only the due date changed: the date of the repetition still holds the old one.
        data = {**fixed, "due_on": "2026-08-01", "repeat_start": "2026-07-01"}
        assert signed_in.post(edit_url(task), data).status_code == 302
        assert services.open_occurrence_of(task).due_on == D(2026, 8, 1)  # type: ignore[union-attr]
        # Only the date of the repetition changed.
        data = {**fixed, "due_on": "2026-08-01", "repeat_start": "2026-09-01"}
        assert signed_in.post(edit_url(task), data).status_code == 302
        assert services.open_occurrence_of(task).due_on == D(2026, 9, 1)  # type: ignore[union-attr]
        # Both changed, to two different dates: refused, nothing moves.
        data = {**fixed, "due_on": "2026-10-01", "repeat_start": "2026-11-01"}
        response = signed_in.post(edit_url(task), data)
        assert response.status_code == 200
        assert "Give the same date as the due date." in response.text
        assert services.open_occurrence_of(task).due_on == D(2026, 9, 1)  # type: ignore[union-attr]

    def test_months_of_a_custom_season_are_ignored_for_another(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        data = {**BASE, "season": "", "season_start_month": "", "season_end_month": "3"}
        response = signed_in.post(create_url(alice_home), data)
        assert response.status_code == 302
        task = Task.objects.get()
        assert (task.season, task.season_start_month, task.season_end_month) == ("", None, None)


class TestTheFormShows:
    def test_the_sentence_and_its_fields(self, signed_in: Client, alice_home: Home) -> None:
        page = signed_in.get(create_url(alice_home)).text
        assert 'name="repeats"' in page
        assert 'name="repeat_mode"' not in page
        assert "Repeat every" in page
        assert "Count from" in page
        assert 'value="fixed"' in page
        assert "the due date" in page
        assert 'value="after_last"' in page
        assert "the day it is done" in page
        assert 'name="repeat_start"' in page
        assert 'type="date"' in page
        assert 'data-shown-when="repeat_from=fixed"' in page
        assert 'data-shown-when="repeat_from=after_last"' in page
        assert 'data-shown-when="season=custom"' in page
        assert "counted from the day the task is marked done" in page
        assert "js/task-form.js" in page
        assert summary_url(alice_home) in page
        assert "Not repeated: the task is done once." in page

    def test_an_existing_task_shows_its_repetition_and_its_custom_season(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        task = services.create_task(
            alice,
            alice_home,
            title="Bleed the radiators",
            repeat_mode="fixed",
            repeat_unit="month",
            repeat_interval=3,
            season="custom",
            season_start_month=10,
            season_end_month=4,
            due_on=D(2027, 1, 15),
        )
        page = signed_in.get(edit_url(task)).text
        assert 'name="repeats" id="id_repeats" checked' in page
        assert 'value="fixed" id="id_repeat_from_0" checked' in page
        assert 'name="repeat_start" value="2027-01-15"' in page
        assert '<option value="custom" selected>' in page
        assert '<option value="10" selected>' in page
        assert "Day 15 of every quarter, from Jan 15, 2027." in page

    def test_the_summary_follows_the_fields(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.get(
            summary_url(alice_home),
            {
                "repeats": "on",
                "repeat_from": "after_last",
                "repeat_interval": "3",
                "repeat_unit": "month",
            },
        )
        assert response.status_code == 200
        assert response.text == "Next time: 3 months after the last time."
        assert response["Cache-Control"] == "no-store"

    def test_the_summary_is_in_the_language_of_the_person(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        response = signed_in.get(
            summary_url(alice_home),
            {
                "repeats": "on",
                "repeat_from": "fixed",
                "repeat_interval": "3",
                "repeat_unit": "month",
                "due_on": "2027-01-15",
                "season": "spring",
            },
            headers={"Accept-Language": "fr"},
        )
        assert response.text == (
            "Le 15 de chaque trimestre à partir du 15 janv. 2027. Seulement entre mars et mai : "
            "une date en dehors passe au 1er mars."
        )

    def test_the_summary_is_for_members_who_may_write(
        self, client: Client, reader: User, alice_home: Home
    ) -> None:
        client.force_login(reader)
        assert client.get(summary_url(alice_home)).status_code == 403

    def test_the_season_follows_the_hemisphere_in_the_summary(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        home_services.update_home(alice, alice_home, hemisphere="south")
        text = signed_in.get(
            summary_url(alice_home),
            {"repeats": "on", "repeat_interval": "1", "repeat_unit": "year", "season": "summer"},
        ).text
        assert text.endswith(
            "Only from December to February: a date outside moves to the first day of December."
        )


def say(**values: Any) -> str:
    return repeat_text.summary(**{"unit": "month", "interval": 1, "start": None, **values})


class TestSentences:
    def test_once(self) -> None:
        assert say(mode="once") == "Not repeated: the task is done once."

    @pytest.mark.parametrize(
        ("unit", "interval", "text"),
        [
            ("day", 1, "Next time: 1 day after the last time."),
            ("week", 2, "Next time: 2 weeks after the last time."),
            ("month", 3, "Next time: 3 months after the last time."),
            ("year", 1, "Next time: 1 year after the last time."),
        ],
    )
    def test_after_the_last_time(self, unit: str, interval: int, text: str) -> None:
        assert say(mode="after_last", unit=unit, interval=interval) == text

    @pytest.mark.parametrize(
        ("unit", "interval", "start", "text"),
        [
            ("day", 1, D(2027, 1, 15), "Every day, from Jan 15, 2027."),
            ("day", 10, D(2027, 1, 15), "Every 10 days, from Jan 15, 2027."),
            ("week", 1, D(2027, 1, 15), "Every Friday, from Jan 15, 2027."),
            ("week", 2, D(2027, 1, 15), "Every 2 weeks on Friday, from Jan 15, 2027."),
            ("month", 1, D(2027, 1, 15), "Day 15 of every month, from Jan 15, 2027."),
            ("month", 3, D(2027, 1, 15), "Day 15 of every quarter, from Jan 15, 2027."),
            ("month", 6, D(2027, 1, 15), "Day 15, every 6 months, from Jan 15, 2027."),
            (
                "month",
                1,
                D(2027, 1, 31),
                "Day 31 of every month, from Jan 31, 2027. In a shorter month, its last day.",
            ),
            ("year", 1, D(2027, 1, 15), "Every year on Jan 15, from Jan 15, 2027."),
            (
                "year",
                4,
                D(2028, 2, 29),
                "Every 4 years on Feb 29, from Feb 29, 2028. In other years, 28 February.",
            ),
        ],
    )
    def test_from_the_due_date(self, unit: str, interval: int, start: D, text: str) -> None:
        assert say(mode="fixed", unit=unit, interval=interval, start=start) == text

    def test_from_the_due_date_without_a_date(self) -> None:
        assert say(mode="fixed") == "Give the date to count from."

    def test_the_largest_interval_and_beyond(self) -> None:
        assert say(mode="after_last", unit="year", interval=50) == (
            "Next time: 50 years after the last time."
        )
        assert say(mode="after_last", unit="year", interval=51) == "This interval is out of range."
        assert say(mode="after_last", interval=None) == "Give how often the task comes back."

    def test_a_season_over_the_new_year(self) -> None:
        assert say(mode="after_last", season=(10, 4)) == (
            "Next time: 1 month after the last time. Only from October to April: a date "
            "outside moves to the first day of October."
        )

    def test_the_words_are_translated_when_said_not_when_loaded(self) -> None:
        with translation.override("fr"):
            assert say(mode="after_last", interval=3) == (
                "Prochaine fois : 3 mois après la dernière fois."
            )
            assert say(mode="fixed", unit="month", start=D(2027, 1, 31)) == (
                "Le 31 de chaque mois à partir du 31 janv. 2027. Dans un mois plus court, le "
                "dernier jour."
            )
        assert say(mode="once") == "Not repeated: the task is done once."

    def test_the_form_summary_reads_its_own_values(self, alice_home: Home) -> None:
        form = TaskForm(
            data={
                "repeats": "on",
                "repeat_from": "fixed",
                "repeat_interval": "1",
                "repeat_unit": "week",
                "repeat_start": "2027-01-15",
            },
            home=alice_home,
        )
        assert repeat_summary(form, alice_home) == "Every Friday, from Jan 15, 2027."
