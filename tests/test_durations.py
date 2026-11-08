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
            (30 * 24 * 60, "30 days"),
        ],
    )
    def test_a_duration_reads_at_a_glance(self, minutes: int, text: str) -> None:
        assert durations.label(minutes) == text

    @pytest.mark.parametrize(
        ("minutes", "shown"),
        [(30, (30, "minute")), (90, (90, "minute")), (120, (2, "hour")), (2880, (2, "day"))],
    )
    def test_the_biggest_exact_unit_is_shown_back(
        self, minutes: int, shown: tuple[int, str]
    ) -> None:
        assert durations.split(minutes) == shown

    def test_units_convert_to_minutes(self) -> None:
        assert durations.to_minutes(3, "hour") == 180
        assert durations.to_minutes(2, "day") == 2880
        assert durations.to_minutes(7, "minute") == 7

    def test_the_bounds(self) -> None:
        assert durations.within_bounds(1)
        assert durations.within_bounds(43200)
        assert not durations.within_bounds(0)
        assert not durations.within_bounds(43201)

    def test_in_french(self) -> None:
        with translation.override("fr"):
            assert durations.label(2 * 24 * 60) == "2 jours"
            assert durations.label(90) == "1 h 30"
            assert durations.label(45) == "45 min"


class TestService:
    @pytest.mark.parametrize("minutes", [0, -5, 43201])
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


class TestScreens:
    @pytest.mark.parametrize(
        ("value", "unit", "minutes"),
        [("45", "minute", 45), ("2", "hour", 120), ("3", "day", 4320)],
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
        ("value", "unit"), [("0", "hour"), ("31", "day"), ("-1", "minute"), ("x", "hour")]
    )
    def test_out_of_bounds_is_refused(
        self, signed_in: Client, alice_home: Home, value: str, unit: str
    ) -> None:
        url = reverse("tasks:create", kwargs={"home_id": alice_home.id})
        response = signed_in.post(url, {**FORM, "duration_value": value, "duration_unit": unit})
        assert response.status_code == 200
        assert not Task.objects.filter(title="Repaint the hall").exists()

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

    @pytest.mark.parametrize("minutes", [0, 43201, -1])
    def test_bounds_are_a_400(
        self, api_client: APIClient, alice: User, alice_home: Home, minutes: int
    ) -> None:
        api_client.force_authenticate(alice)
        url = reverse("api-v1:home-task-list", kwargs={"home_id": alice_home.id})
        response = api_client.post(url, {"title": "x", "estimated_minutes": minutes}, format="json")
        assert response.status_code == 400
        assert "estimated_minutes" in response.json()
