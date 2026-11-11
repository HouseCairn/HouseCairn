"""Seasons of a task: predefined ones that follow the hemisphere of the home (docs/adr/0045)."""

import datetime

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.tasks import recurrence, services
from housecairn.tasks.models import Task

pytest_plugins = ("tests.tasks_fixtures", "tests.rooms_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

FORM = {
    "title": "Service the boiler",
    "priority": "normal",
    "repeat_mode": "once",
    "repeat_interval": "1",
    "repeat_unit": "month",
    "hide_days_before": "0",
}


class TestWindows:
    @pytest.mark.parametrize(
        ("season", "north", "south"),
        [
            ("spring", (3, 5), (9, 11)),
            ("summer", (6, 8), (12, 2)),
            ("autumn", (9, 11), (3, 5)),
            ("winter", (12, 2), (6, 8)),
        ],
    )
    def test_the_southern_hemisphere_is_shifted_by_six_months(
        self, season: str, north: tuple[int, int], south: tuple[int, int]
    ) -> None:
        assert recurrence.season_window(season, "north") == north
        assert recurrence.season_window(season, "south") == south

    def test_the_heating_season_is_no_longer_a_season_but_keeps_its_months(self) -> None:
        assert recurrence.season_window("heating", "north") is None
        assert "heating" not in recurrence.PREDEFINED_SEASONS
        assert recurrence.legacy_season("heating", "north") == (10, 4)
        assert recurrence.legacy_season("heating", "south") == (4, 10)
        assert recurrence.legacy_season("summer", "north") is None
        assert recurrence.legacy_season("heating", "moon") is None

    def test_other_values_have_no_window(self) -> None:
        assert recurrence.season_window("custom", "north") is None
        assert recurrence.season_window("", "north") is None
        assert recurrence.season_window("summer", "moon") is None

    def test_a_southern_summer_is_in_season_in_january(self) -> None:
        rule = recurrence.Rule(season_start=12, season_end=2)
        assert recurrence.in_season(rule, datetime.date(2026, 1, 15))
        assert not recurrence.in_season(rule, datetime.date(2026, 7, 15))


class TestService:
    def test_a_predefined_season_takes_the_window_of_the_home(
        self, alice: User, alice_home: Home
    ) -> None:
        task = services.create_task(alice, alice_home, title="Mow", season="summer")
        assert (task.season_start_month, task.season_end_month) == (6, 8)
        home_services.update_home(alice, alice_home, hemisphere="south")
        task = services.create_task(alice, alice_home, title="Mow again", season="summer")
        assert (task.season_start_month, task.season_end_month) == (12, 2)

    def test_the_hemisphere_moves_the_tasks_already_on_a_predefined_season(
        self, alice: User, alice_home: Home
    ) -> None:
        summer = services.create_task(alice, alice_home, title="Mow", season="summer")
        custom = services.create_task(
            alice,
            alice_home,
            title="Prune",
            season="custom",
            season_start_month=2,
            season_end_month=3,
        )
        year = services.create_task(alice, alice_home, title="Dust")
        home_services.update_home(alice, alice_home, hemisphere="south")
        for task in (summer, custom, year):
            task.refresh_from_db()
        assert (summer.season_start_month, summer.season_end_month) == (12, 2)
        assert (custom.season_start_month, custom.season_end_month) == (2, 3)
        assert year.season_start_month is None
        home_services.update_home(alice, alice_home, hemisphere="north")
        summer.refresh_from_db()
        assert (summer.season_start_month, summer.season_end_month) == (6, 8)

    def test_another_home_is_left_alone(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home
    ) -> None:
        theirs = services.create_task(bob, bob_home, title="Mow", season="summer")
        home_services.update_home(alice, alice_home, hemisphere="south")
        theirs.refresh_from_db()
        assert (theirs.season_start_month, theirs.season_end_month) == (6, 8)

    def test_months_without_a_season_make_a_custom_one(self, alice: User, alice_home: Home) -> None:
        task = services.create_task(
            alice, alice_home, title="Prune", season_start_month=4, season_end_month=6
        )
        assert task.season == "custom"
        services.update_task(alice, task, season_start_month=5)
        task.refresh_from_db()
        assert (task.season, task.season_start_month, task.season_end_month) == ("custom", 5, 6)

    def test_no_season_means_no_months(self, alice: User, alice_home: Home) -> None:
        task = services.create_task(alice, alice_home, title="Mow", season="summer")
        services.update_task(alice, task, season="")
        task.refresh_from_db()
        assert (task.season, task.season_start_month, task.season_end_month) == ("", None, None)

    def test_a_custom_season_needs_both_months(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValidationError):
            services.create_task(alice, alice_home, title="Prune", season="custom")

    def test_an_unknown_season_is_refused(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValidationError):
            services.create_task(alice, alice_home, title="Prune", season="monsoon")

    def test_a_reader_cannot_change_the_hemisphere(self, reader: User, alice_home: Home) -> None:
        with pytest.raises(PermissionDenied):
            home_services.update_home(reader, alice_home, hemisphere="south")

    def test_an_unknown_hemisphere_is_refused(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValidationError):
            home_services.update_home(alice, alice_home, hemisphere="moon")


class TestScreens:
    def test_the_task_form_takes_a_predefined_season(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        url = reverse("tasks:create", kwargs={"home_id": alice_home.id})
        page = signed_in.get(url).text
        assert 'value="summer"' in page
        assert 'value="heating"' not in page
        assert "Heating season" not in page
        assert signed_in.post(url, {**FORM, "season": "summer"}).status_code == 302
        task = Task.objects.get(title="Service the boiler")
        assert (task.season, task.season_start_month, task.season_end_month) == ("summer", 6, 8)

    def test_the_task_form_no_longer_takes_the_heating_season(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        url = reverse("tasks:create", kwargs={"home_id": alice_home.id})
        assert signed_in.post(url, {**FORM, "season": "heating"}).status_code == 200
        assert not Task.objects.exists()

    def test_months_chosen_with_a_predefined_season_are_ignored(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        url = reverse("tasks:create", kwargs={"home_id": alice_home.id})
        data = {**FORM, "season": "summer", "season_start_month": "1", "season_end_month": "2"}
        assert signed_in.post(url, data).status_code == 302
        task = Task.objects.get(title="Service the boiler")
        assert (task.season_start_month, task.season_end_month) == (6, 8)

    def test_a_custom_season_asks_for_its_months(self, signed_in: Client, alice_home: Home) -> None:
        url = reverse("tasks:create", kwargs={"home_id": alice_home.id})
        response = signed_in.post(url, {**FORM, "season": "custom", "season_start_month": "3"})
        assert response.status_code == 200
        assert "Give the first and the last month" in response.text
        done = signed_in.post(
            url, {**FORM, "season": "custom", "season_start_month": "3", "season_end_month": "4"}
        )
        assert done.status_code == 302
        assert Task.objects.get(title="Service the boiler").season == "custom"

    def test_the_form_names_the_hemisphere(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        home_services.update_home(alice, alice_home, hemisphere="south")
        page = signed_in.get(reverse("tasks:create", kwargs={"home_id": alice_home.id})).text
        assert "hemisphere of the home (southern)" in page

    def test_the_task_page_says_the_season(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        task = services.create_task(
            alice,
            alice_home,
            title="Bleed",
            season="winter",
            repeat_mode="fixed",
            repeat_unit="year",
            due_on=datetime.date(2026, 12, 20),
        )
        page = signed_in.get(
            reverse("tasks:detail", kwargs={"home_id": alice_home.id, "task_id": task.id})
        ).text
        assert "Winter" in page


class TestHomeScreen:
    def test_the_hemisphere_is_set_on_the_home_screen(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        url = reverse("homes:edit", kwargs={"home_id": alice_home.id})
        assert 'name="hemisphere"' in signed_in.get(url).text
        response = signed_in.post(
            url, {"name": "Main house", "currency": "EUR", "hemisphere": "south"}
        )
        assert response.status_code == 302
        alice_home.refresh_from_db()
        assert alice_home.hemisphere == "south"

    def test_a_new_home_is_northern_by_default_and_can_be_southern(self, signed_in: Client) -> None:
        signed_in.post(
            reverse("homes:create"), {"name": "Cottage", "currency": "AUD", "hemisphere": "south"}
        )
        assert Home.objects.get(name="Cottage").hemisphere == "south"
        assert Home(name="x").hemisphere == "north"

    def test_a_reader_cannot_open_the_screen(
        self, client: Client, reader: User, alice_home: Home
    ) -> None:
        client.force_login(reader)
        url = reverse("homes:edit", kwargs={"home_id": alice_home.id})
        assert client.get(url).status_code == 403
        assert (
            client.post(url, {"name": "x", "currency": "EUR", "hemisphere": "south"}).status_code
            == 403
        )
        alice_home.refresh_from_db()
        assert alice_home.hemisphere == "north"

    def test_another_home_is_a_404(self, signed_in: Client, bob_home: Home) -> None:
        assert (
            signed_in.get(reverse("homes:edit", kwargs={"home_id": bob_home.id})).status_code == 404
        )


class TestApi:
    def test_the_hemisphere_and_the_season_through_the_api(
        self, api_client: APIClient, alice: User, alice_home: Home
    ) -> None:
        api_client.force_authenticate(alice)
        home_url = reverse("api-v1:home-detail", kwargs={"home_id": alice_home.id})
        assert api_client.get(home_url).json()["hemisphere"] == "north"
        assert api_client.patch(home_url, {"hemisphere": "south"}, format="json").status_code == 200
        created = api_client.post(
            reverse("api-v1:home-task-list", kwargs={"home_id": alice_home.id}),
            {"title": "Mow", "season": "summer"},
            format="json",
        )
        assert created.status_code == 201
        body = created.json()
        assert (body["season"], body["season_start_month"], body["season_end_month"]) == (
            "summer",
            12,
            2,
        )
        assert api_client.patch(home_url, {"hemisphere": "moon"}, format="json").status_code == 400

    def test_a_reader_cannot_change_it(
        self, api_client: APIClient, reader: User, alice_home: Home
    ) -> None:
        api_client.force_authenticate(reader)
        home_url = reverse("api-v1:home-detail", kwargs={"home_id": alice_home.id})
        assert api_client.patch(home_url, {"hemisphere": "south"}, format="json").status_code == 403
