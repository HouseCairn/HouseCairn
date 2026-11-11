"""Estimated duration: a number and a unit, minutes in the data (docs/adr/0045)."""

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import translation
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.tasks import durations, services
from housecairn.tasks.models import Task

pytest_plugins = ("tests.tasks_fixtures", "tests.rooms_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

DAY = 24 * 60

FORM = {
    "title": "Repaint the hall",
    "priority": "normal",
    "repeat_mode": "once",
    "repeat_interval": "1",
    "repeat_unit": "month",
    "hide_days_before": "0",
}


class TestHelpers:
    @pytest.mark.parametrize(
        ("minutes", "text"),
        [
            (1, "1 min"),
            (45, "45 min"),
            (60, "1 h"),
            (90, "1 h 30"),
            (125, "2 h 05"),
            (24 * 60, "1 day"),
            (2 * 24 * 60, "2 days"),
            (26 * 60 + 30, "1 day 2 h 30"),
            (24 * 60 + 15, "1 day 15 min"),
            (6 * DAY, "6 days"),
            (7 * DAY, "1 week"),
            (10 * DAY + 60, "1 week 3 days 1 h"),
            (14 * DAY, "2 weeks"),
            (30 * DAY, "1 month"),
            (45 * DAY, "1 month 2 weeks 1 day"),
            (90 * DAY, "3 months"),
            (365 * DAY, "1 year"),
        ],
    )
    def test_a_duration_reads_at_a_glance(self, minutes: int, text: str) -> None:
        assert durations.label(minutes) == text

    @pytest.mark.parametrize(
        ("minutes", "shown"),
        [
            (30, (30, "minute")),
            (90, (90, "minute")),
            (120, (2, "hour")),
            (2880, (2, "day")),
            (14 * DAY, (2, "week")),
            (60 * DAY, (2, "month")),
            (365 * DAY, (1, "year")),
            (10 * DAY, (10, "day")),
        ],
    )
    def test_the_biggest_exact_unit_is_shown_back(
        self, minutes: int, shown: tuple[int, str]
    ) -> None:
        assert durations.split(minutes) == shown

    def test_units_convert_to_minutes(self) -> None:
        assert durations.to_minutes(3, "hour") == 180
        assert durations.to_minutes(2, "day") == 2880
        assert durations.to_minutes(7, "minute") == 7
        # A week is seven days, a month thirty days and a year 365 days.
        assert durations.to_minutes(1, "week") == 7 * DAY
        assert durations.to_minutes(1, "month") == 30 * DAY
        assert durations.to_minutes(1, "year") == 365 * DAY

    def test_the_bounds(self) -> None:
        assert durations.MAX_MINUTES == 365 * DAY
        assert durations.within_bounds(1)
        assert durations.within_bounds(365 * DAY)
        assert not durations.within_bounds(0)
        assert not durations.within_bounds(365 * DAY + 1)

    def test_the_units_of_the_form(self) -> None:
        assert [code for code, _ in durations.UNIT_CHOICES] == [
            "minute",
            "hour",
            "day",
            "week",
            "month",
            "year",
        ]

    def test_in_french(self) -> None:
        with translation.override("fr"):
            assert durations.label(2 * 24 * 60) == "2 jours"
            assert durations.label(90) == "1 h 30"
            assert durations.label(45) == "45 min"
            assert durations.label(14 * DAY) == "2 semaines"
            assert durations.label(60 * DAY) == "2 mois"
            assert durations.label(365 * DAY) == "1 an"
            assert durations.bounds_message() == "Indiquez une durée entre 1 min et 1 an."


class TestService:
    @pytest.mark.parametrize("minutes", [0, -5, 365 * DAY + 1])
    def test_the_bounds_are_the_business_ones(
        self, alice: User, alice_home: Home, minutes: int
    ) -> None:
        with pytest.raises(ValidationError) as caught:
            services.create_task(alice, alice_home, title="x", estimated_minutes=minutes)
        assert "estimated_minutes" in caught.value.message_dict

    def test_no_duration_is_fine(self, alice: User, alice_home: Home) -> None:
        task = services.create_task(alice, alice_home, title="x")
        services.update_task(alice, task, estimated_minutes=90)
        services.update_task(alice, task, estimated_minutes=None)
        task.refresh_from_db()
        assert task.estimated_minutes is None

    def test_a_task_kept_at_zero_can_be_edited_for_something_else(
        self, alice: User, alice_home: Home
    ) -> None:
        task = services.create_task(alice, alice_home, title="Old")
        Task.objects.filter(pk=task.pk).update(estimated_minutes=0)  # accepted before the bound
        task.refresh_from_db()
        services.update_task(alice, task, title="Renamed")
        task.refresh_from_db()
        assert (task.title, task.estimated_minutes) == ("Renamed", 0)

    def test_the_bound_still_holds_when_the_duration_changes(
        self, alice: User, alice_home: Home
    ) -> None:
        task = services.create_task(alice, alice_home, title="x", estimated_minutes=30)
        with pytest.raises(ValidationError) as caught:
            services.update_task(alice, task, estimated_minutes=0)
        assert "estimated_minutes" in caught.value.message_dict


class TestScreens:
    @pytest.mark.parametrize(
        ("value", "unit", "minutes"),
        [
            ("45", "minute", 45),
            ("2", "hour", 120),
            ("3", "day", 4320),
            ("2", "week", 14 * DAY),
            ("6", "month", 180 * DAY),
            ("1", "year", 365 * DAY),
        ],
    )
    def test_the_form_stores_minutes(
        self, signed_in: Client, alice_home: Home, value: str, unit: str, minutes: int
    ) -> None:
        url = reverse("tasks:create", kwargs={"home_id": alice_home.id})
        data = {**FORM, "duration_value": value, "duration_unit": unit}
        assert signed_in.post(url, data).status_code == 302
        assert Task.objects.get(title="Repaint the hall").estimated_minutes == minutes

    def test_the_form_shows_it_back_in_the_biggest_exact_unit(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        task = services.create_task(alice, alice_home, title="Paint", estimated_minutes=2880)
        page = signed_in.get(
            reverse("tasks:edit", kwargs={"home_id": alice_home.id, "task_id": task.id})
        ).text
        assert 'name="duration_value"' in page
        assert 'value="2"' in page
        assert '<option value="day" selected>' in page

    @pytest.mark.parametrize(
        ("value", "unit"),
        [
            ("0", "hour"),
            ("366", "day"),
            ("13", "month"),
            ("2", "year"),
            ("53", "week"),
            ("-1", "minute"),
            ("x", "hour"),
        ],
    )
    def test_out_of_bounds_is_refused(
        self, signed_in: Client, alice_home: Home, value: str, unit: str
    ) -> None:
        url = reverse("tasks:create", kwargs={"home_id": alice_home.id})
        response = signed_in.post(url, {**FORM, "duration_value": value, "duration_unit": unit})
        assert response.status_code == 200
        assert not Task.objects.filter(title="Repaint the hall").exists()

    def test_the_ceiling_is_said_on_the_form(self, signed_in: Client, alice_home: Home) -> None:
        url = reverse("tasks:create", kwargs={"home_id": alice_home.id})
        response = signed_in.post(url, {**FORM, "duration_value": "2", "duration_unit": "year"})
        assert "Give a duration between 1 min and 1 year." in response.text

    def test_thirty_one_days_is_now_accepted(self, signed_in: Client, alice_home: Home) -> None:
        url = reverse("tasks:create", kwargs={"home_id": alice_home.id})
        response = signed_in.post(url, {**FORM, "duration_value": "31", "duration_unit": "day"})
        assert response.status_code == 302
        assert Task.objects.get(title="Repaint the hall").estimated_minutes == 31 * DAY

    def test_the_task_page_reads_the_duration(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        task = services.create_task(alice, alice_home, title="Paint", estimated_minutes=90)
        page = signed_in.get(
            reverse("tasks:detail", kwargs={"home_id": alice_home.id, "task_id": task.id})
        ).text
        assert "1 h 30" in page


class TestApi:
    def test_minutes_in_and_a_readable_text_out(
        self, api_client: APIClient, alice: User, alice_home: Home
    ) -> None:
        api_client.force_authenticate(alice)
        url = reverse("api-v1:home-task-list", kwargs={"home_id": alice_home.id})
        body = api_client.post(url, {"title": "Paint", "estimated_minutes": 90}, format="json")
        assert body.status_code == 201
        assert body.json()["estimated_minutes"] == 90
        assert body.json()["estimated_text"] == "1 h 30"
        none = api_client.post(url, {"title": "Dust"}, format="json").json()
        assert none["estimated_minutes"] is None
        assert none["estimated_text"] == ""

    @pytest.mark.parametrize("minutes", [0, 365 * DAY + 1, -1])
    def test_bounds_are_a_400(
        self, api_client: APIClient, alice: User, alice_home: Home, minutes: int
    ) -> None:
        api_client.force_authenticate(alice)
        url = reverse("api-v1:home-task-list", kwargs={"home_id": alice_home.id})
        response = api_client.post(url, {"title": "x", "estimated_minutes": minutes}, format="json")
        assert response.status_code == 400
        assert "estimated_minutes" in response.json()

    def test_a_task_kept_at_zero_takes_a_patch_of_another_field(
        self, api_client: APIClient, alice: User, alice_home: Home
    ) -> None:
        task = services.create_task(alice, alice_home, title="Old")
        Task.objects.filter(pk=task.pk).update(estimated_minutes=0)
        api_client.force_authenticate(alice)
        url = reverse(
            "api-v1:home-task-detail", kwargs={"home_id": alice_home.id, "task_id": task.id}
        )
        response = api_client.patch(url, {"title": "Renamed"}, format="json")
        assert response.status_code == 200, response.content
        assert response.json()["title"] == "Renamed"
        # Sending a duration of 0 is still refused: the bound holds for what is written.
        assert api_client.patch(url, {"estimated_minutes": 0}, format="json").status_code == 400
