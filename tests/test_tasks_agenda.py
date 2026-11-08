"""Today, My home, History and display preferences: layout, isolation, roles, API."""

import datetime
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.rooms import services as room_services
from housecairn.rooms.models import Room
from housecairn.tasks import agenda, services
from housecairn.tasks.models import DisplayPreference, Occurrence, Task
from tests.tasks_fixtures import TODAY

pytest_plugins = (
    "tests.tasks_fixtures",
    "tests.rooms_fixtures",
)
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

DAY = timedelta(days=1)


def web(name: str, home: Home) -> str:
    return reverse(f"tasks:{name}", kwargs={"home_id": home.id})


def api(name: str, home: Home | None = None, **kwargs: object) -> str:
    if home is not None:
        kwargs["home_id"] = home.id
    return reverse(f"api-v1:{name}", kwargs=kwargs)


def titles(sections: list[agenda.Section]) -> dict[str, list[str]]:
    return {s.key + ":" + s.title: [o.task.title for o in s.rows] for s in sections}


@pytest.fixture
def bathroom(alice: User, alice_home: Home) -> Room:
    return room_services.create_room(alice, alice_home, name="Bathroom", kind="bathroom")


@pytest.fixture
def busy(alice: User, member: User, alice_home: Home, owner_room: Room, bathroom: Room) -> Home:
    """Late, today, soon, far, seasonal and dateless tasks, in two rooms, for two people."""
    make = services.create_task
    make(alice, alice_home, title="Late one", due_on=TODAY - 3 * DAY, room=owner_room)
    make(
        alice,
        alice_home,
        title="Late and urgent",
        due_on=TODAY - 3 * DAY,
        priority="high",
        room=bathroom,
        assignee=member,
    )
    make(alice, alice_home, title="Due today", due_on=TODAY, room=bathroom, assignee=alice)
    make(alice, alice_home, title="Due soon", due_on=TODAY + 3 * DAY, room=owner_room)
    make(alice, alice_home, title="Due in a month", due_on=TODAY + 30 * DAY)
    make(
        alice,
        alice_home,
        title="Mow the lawn",
        due_on=TODAY + 40 * DAY,
        repeat_mode="fixed",
        repeat_unit="week",
        season_start_month=4,
        season_end_month=10,
    )
    make(
        alice,
        alice_home,
        title="Heat the pipes",
        due_on=TODAY + 40 * DAY,
        repeat_mode="fixed",
        repeat_unit="week",
        season_start_month=11,
        season_end_month=12,
    )
    make(
        alice,
        alice_home,
        title="Hidden for now",
        due_on=TODAY + 5 * DAY,
        hide_days_before=2,
    )
    return alice_home


class TestPreferences:
    def test_defaults_until_a_change(self, alice: User) -> None:
        prefs = agenda.preferences_of(alice)
        assert (prefs.today_group, prefs.horizon_days) == ("urgency", 7)
        assert (prefs.show_overdue, prefs.show_upcoming, prefs.show_season) == (True,) * 3
        assert DisplayPreference.objects.count() == 0

    def test_a_change_is_kept_for_that_person_only(self, alice: User, bob: User) -> None:
        agenda.update_preferences(alice, today_group="room", horizon_days=30, show_season=False)
        agenda.update_preferences(alice, today_group="person")
        mine = agenda.preferences_of(alice)
        assert (mine.today_group, mine.horizon_days, mine.show_season) == ("person", 30, False)
        assert agenda.preferences_of(bob).today_group == "urgency"
        assert DisplayPreference.objects.count() == 1

    def test_invalid_values_are_refused(self, alice: User) -> None:
        with pytest.raises(ValidationError):
            agenda.update_preferences(alice, today_group="colour")
        with pytest.raises(ValidationError):
            agenda.update_preferences(alice, horizon_days=8)
        with pytest.raises(ValueError, match="user"):
            agenda.update_preferences(alice, user=alice)

    def test_nobody_changes_the_preferences_of_a_visitor(self) -> None:
        from django.contrib.auth.models import AnonymousUser

        with pytest.raises(PermissionDenied):
            agenda.update_preferences(AnonymousUser(), today_group="room")

    def test_they_go_with_the_account(self, make_user: Callable[..., User]) -> None:
        leaving = make_user("leaving@example.com")
        agenda.update_preferences(leaving, today_group="room")
        leaving.delete()
        assert DisplayPreference.objects.count() == 0


class TestToday:
    def test_urgency_by_default_with_the_arrears_first(self, busy: Home, alice: User) -> None:
        sections = agenda.today_sections(busy, agenda.preferences_of(alice))
        assert titles(sections) == {
            "overdue:Overdue": ["Late and urgent", "Late one"],
            "today:Today": ["Due today"],
            "upcoming:Coming up": ["Due soon"],
            "season:In season": ["Mow the lawn"],
        }

    def test_hidden_tasks_stay_hidden_until_their_day(self, busy: Home, alice: User) -> None:
        everything = [
            o.task.title
            for s in agenda.today_sections(busy, agenda.preferences_of(alice), day=TODAY + 4 * DAY)
            for o in s.rows
        ]
        assert "Hidden for now" in everything
        today = [
            o.task.title
            for s in agenda.today_sections(busy, agenda.preferences_of(alice))
            for o in s.rows
        ]
        assert "Hidden for now" not in today

    def test_the_horizon_widens_the_coming_section(self, busy: Home, alice: User) -> None:
        agenda.update_preferences(alice, horizon_days=30)
        sections = titles(agenda.today_sections(busy, agenda.preferences_of(alice)))
        assert sections["upcoming:Coming up"] == ["Due soon", "Due in a month"]

    def test_by_room(self, busy: Home, alice: User) -> None:
        agenda.update_preferences(alice, today_group="room", horizon_days=30)
        sections = agenda.today_sections(busy, agenda.preferences_of(alice))
        assert titles(sections) == {
            "overdue:Overdue": ["Late and urgent", "Late one"],
            "room:Bathroom": ["Due today"],
            "room:Living room": ["Due soon"],
            "room:No room": ["Due in a month"],
            "season:In season": ["Mow the lawn"],
        }
        assert sections[1].ref
        assert sections[3].ref is None

    def test_by_person(self, busy: Home, alice: User) -> None:
        agenda.update_preferences(alice, today_group="person", horizon_days=30)
        sections = titles(agenda.today_sections(busy, agenda.preferences_of(alice)))
        assert sections["person:alice@example.com"] == ["Due today"]
        assert sections["person:Nobody yet"] == ["Due soon", "Due in a month"]
        assert list(sections)[-3:-1] == ["person:alice@example.com", "person:Nobody yet"]

    def test_by_calendar(self, busy: Home, alice: User) -> None:
        agenda.update_preferences(alice, today_group="calendar")
        sections = agenda.today_sections(busy, agenda.preferences_of(alice))
        days = [s.day for s in sections if s.key == "day"]
        assert days == [TODAY, TODAY + 3 * DAY]

    def test_a_section_can_be_switched_off(self, busy: Home, alice: User) -> None:
        agenda.update_preferences(alice, show_overdue=False, show_season=False)
        keys = [s.key for s in agenda.today_sections(busy, agenda.preferences_of(alice))]
        assert keys == ["today", "upcoming"]
        agenda.update_preferences(alice, show_upcoming=False)
        assert agenda.today_sections(busy, agenda.preferences_of(alice)) == []

    def test_a_task_in_season_without_a_date_is_listed(self, alice: User, alice_home: Home) -> None:
        services.create_task(
            alice, alice_home, title="Prune", season_start_month=5, season_end_month=7
        )
        sections = titles(agenda.today_sections(alice_home, agenda.preferences_of(alice)))
        assert sections == {"season:In season": ["Prune"]}

    def test_closed_tasks_are_not_listed(
        self, alice: User, alice_home: Home, owner_occurrence: Occurrence
    ) -> None:
        services.complete(alice, owner_occurrence)
        sections = titles(agenda.today_sections(alice_home, agenda.preferences_of(alice)))
        assert all(
            "Change the smoke detector battery" not in rows
            for key, rows in sections.items()
            if key.startswith("overdue")
        )


class TestMyHome:
    def test_four_blocks_that_share_no_row(
        self, busy: Home, alice: User, member: User, owner_room: Room
    ) -> None:
        item = room_services.create_item(
            alice,
            owner_room,
            name="Dishwasher",
            warranty_ends_on=TODAY + 20 * DAY,
        )
        room_services.create_item(
            alice, owner_room, name="Old fridge", warranty_ends_on=TODAY - DAY
        )
        room_services.create_item(
            alice, owner_room, name="New oven", warranty_ends_on=TODAY + 400 * DAY
        )
        (digest,) = agenda.my_home(alice, [busy])
        assert [o.task.title for o in digest.mine] == ["Due today"]
        assert [o.task.title for o in digest.overdue] == ["Late and urgent", "Late one"]
        assert [o.task.title for o in digest.unassigned] == [
            "Due soon",
            "Due in a month",
            "Mow the lawn",
            "Heat the pipes",
        ]
        assert [i.id for i in digest.warranties] == [item.id]
        (theirs,) = agenda.my_home(member, [busy])
        assert [o.task.title for o in theirs.mine] == ["Late and urgent"]
        assert "Late and urgent" not in [o.task.title for o in theirs.overdue]

    def test_a_home_with_nothing(self, alice: User, alice_home: Home) -> None:
        (digest,) = agenda.my_home(alice, [alice_home])
        assert digest.empty

    def test_the_rights_of_the_person_in_each_home(
        self, alice: User, reader: User, alice_home: Home
    ) -> None:
        assert agenda.my_home(alice, [alice_home])[0].can_write is True
        assert agenda.my_home(reader, [alice_home])[0].can_write is False


class TestHistory:
    @pytest.fixture
    def past(self, busy: Home, alice: User, member: User, owner_room: Room) -> Home:
        plumber = services.create_contractor(alice, busy, name="Pipes Ltd", trade="plumber")
        work = services.create_task(
            alice,
            busy,
            title="Fix the tap",
            room=owner_room,
            contractor=plumber,
            due_on=TODAY - 20 * DAY,
        )
        services.complete(
            alice,
            services.open_occurrence_of(work),
            on=TODAY - 10 * DAY,
            actual_cost=Decimal("80.50"),
            note="New washer",
        )
        paint = services.create_task(alice, busy, title="Paint the hall", due_on=TODAY - 9 * DAY)
        services.complete(member, services.open_occurrence_of(paint), actual_cost=Decimal("19.50"))
        gutters = services.create_task(alice, busy, title="Clean the gutters")
        services.skip(alice, services.open_occurrence_of(gutters))
        return busy

    def search(self, home: Home, **filters: object) -> list[str]:
        rows = agenda.history(home, agenda.HistoryFilter(**filters))  # type: ignore[arg-type]
        return [o.task.title for o in rows]

    def test_everything_closed_the_latest_first(self, past: Home) -> None:
        assert self.search(past) == ["Clean the gutters", "Paint the hall", "Fix the tap"]

    def test_each_filter(self, past: Home, alice: User, member: User, owner_room: Room) -> None:
        plumber = services.contractors_of(past).get()
        assert self.search(past, room=owner_room.id) == ["Fix the tap"]
        assert self.search(past, contractor=plumber.id) == ["Fix the tap"]
        assert self.search(past, person=member.id) == ["Paint the hall"]
        assert self.search(past, status="skipped") == ["Clean the gutters"]
        assert self.search(past, status="done") == ["Paint the hall", "Fix the tap"]
        assert self.search(past, query="washer") == ["Fix the tap"]
        assert self.search(past, query="PAINT") == ["Paint the hall"]
        assert self.search(past, query="nothing like this") == []
        assert self.search(past, after=TODAY - 5 * DAY) == ["Clean the gutters", "Paint the hall"]
        assert self.search(past, before=TODAY - 5 * DAY) == ["Fix the tap"]
        item = room_services.create_item(alice, owner_room, name="Tap")
        assert self.search(past, item=item.id) == []

    def test_the_cost_counts_only_what_was_entered(self, past: Home) -> None:
        cost = agenda.cost_of(agenda.history(past, agenda.HistoryFilter()))
        assert (cost.total, cost.with_cost, cost.count) == (Decimal("100.00"), 2, 3)
        none = agenda.cost_of(agenda.history(past, agenda.HistoryFilter(query="nothing")))
        assert (none.total, none.with_cost, none.count) == (Decimal("0.00"), 0, 0)

    def test_another_home_is_never_listed(self, past: Home, bob: User, bob_home: Home) -> None:
        other = services.create_task(bob, bob_home, title="Bob's chore")
        services.complete(bob, services.open_occurrence_of(other))
        assert "Bob's chore" not in self.search(past)
        assert self.search(bob_home) == ["Bob's chore"]


class TestScreens:
    def test_today_lays_out_the_sections(self, busy: Home, signed_in: Client) -> None:
        response = signed_in.get(web("today", busy))
        content = response.content.decode()
        assert response.status_code == 200
        assert content.index("Overdue") < content.index("Late one") < content.index("Due today")
        assert content.index("Due today") < content.index("Due soon")
        assert "Mow the lawn" in content
        assert "Done" in content

    def test_done_in_one_tap_and_undo_from_today(
        self, busy: Home, signed_in: Client, alice: User
    ) -> None:
        occurrence = services.open_occurrences(busy).get(task__title="Due today")
        action = reverse(
            "tasks:complete",
            kwargs={
                "home_id": busy.id,
                "task_id": occurrence.task_id,
                "occurrence_id": occurrence.id,
            },
        )
        back = signed_in.post(action, {"next": web("today", busy)}, follow=True)
        assert back.redirect_chain[-1][0].startswith(web("today", busy))
        assert "Marked done." in back.content.decode()
        assert Occurrence.objects.get(id=occurrence.id).status == "done"
        undo = reverse(
            "tasks:undo",
            kwargs={
                "home_id": busy.id,
                "task_id": occurrence.task_id,
                "occurrence_id": occurrence.id,
            },
        )
        signed_in.post(undo, {"next": web("today", busy)})
        assert Occurrence.objects.get(id=occurrence.id).status == "planned"

    def test_the_layout_follows_the_preferences(self, busy: Home, signed_in: Client) -> None:
        signed_in.post(
            reverse("display-preferences"),
            {
                "today_group": "room",
                "horizon_days": "30",
                "show_overdue": "on",
                "show_upcoming": "on",
            },
        )
        content = signed_in.get(web("today", busy)).content.decode()
        assert "Bathroom" in content
        assert "Due in a month" in content
        assert "In season" not in content
        assert "Coming up" not in content

    def test_the_calendar_layout_shows_days(self, busy: Home, signed_in: Client) -> None:
        agenda.update_preferences(
            User.objects.get(email="alice@example.com"), today_group="calendar"
        )
        assert signed_in.get(web("today", busy)).status_code == 200

    def test_empty_today(self, alice_home: Home, signed_in: Client) -> None:
        assert "Nothing to do for now." in signed_in.get(web("today", alice_home)).content.decode()

    def test_the_reader_sees_no_button(self, busy: Home, reader: User, client: Client) -> None:
        client.force_login(reader)
        content = client.get(web("today", busy)).content.decode()
        assert "Due today" in content
        assert "Add a task" not in content
        assert "/complete/" not in content

    def test_my_home_selects_a_home(self, busy: Home, alice: User, signed_in: Client) -> None:
        second = home_services.create_home(alice, name="Holiday flat")
        services.create_task(alice, second, title="Close the shutters", assignee=alice)
        both = signed_in.get(reverse("my-home")).content.decode()
        assert "Holiday flat" in both
        assert "Close the shutters" in both
        assert "Due today" in both
        one = signed_in.get(reverse("my-home"), {"home": str(second.id)}).content.decode()
        assert "Close the shutters" in one
        assert "Due today" not in one
        unknown = signed_in.get(reverse("my-home"), {"home": "nonsense"}).content.decode()
        assert "Due today" in unknown

    def test_my_home_without_a_home(self, client: Client, make_user: Callable[..., User]) -> None:
        client.force_login(make_user("alone@example.com"))
        assert "You have no home to open yet." in client.get(reverse("my-home")).content.decode()

    def test_navigation_leads_home(self, signed_in: Client, alice_home: Home) -> None:
        content = signed_in.get(reverse("more")).content.decode()
        assert f'href="{reverse("my-home")}"' in content
        assert content.count('aria-current="page"') == 1
        anonymous = Client().get(reverse("index")).content.decode()
        assert reverse("my-home") not in anonymous

    def test_history_page(self, signed_in: Client, past: Home) -> None:
        response = signed_in.get(web("history", past))
        content = response.content.decode()
        assert response.status_code == 200
        assert content.index("Clean the gutters") < content.index("Paint the hall")
        assert "100.00 EUR" in content
        filtered = signed_in.get(web("history", past), {"q": "washer", "status": "done"})
        assert "Fix the tap" in filtered.content.decode()
        assert "Paint the hall" not in filtered.content.decode()
        nothing = signed_in.get(web("history", past), {"q": "zzz"}).content.decode()
        assert "Nothing matches." in nothing

    def test_history_ignores_what_is_not_a_filter(self, signed_in: Client, past: Home) -> None:
        for params in (
            {"room": "x", "after": "not a date", "before": "2026-13-45", "status": "open"},
            {"item": "x", "contractor": "x", "person": "x", "page": "9999"},
        ):
            assert signed_in.get(web("history", past), params).status_code == 200

    def test_history_pages_keep_the_filters(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        for number in range(35):
            task = services.create_task(alice, alice_home, title=f"Chore {number}")
            services.complete(alice, services.open_occurrence_of(task))
        content = signed_in.get(web("history", alice_home), {"q": "Chore"}).content.decode()
        assert "?q=Chore&amp;page=2" in content

    def test_history_of_an_empty_home(self, signed_in: Client, alice_home: Home) -> None:
        assert "Nothing done yet." in signed_in.get(web("history", alice_home)).content.decode()

    def test_preferences_form(self, signed_in: Client, alice: User) -> None:
        assert signed_in.get(reverse("display-preferences")).status_code == 200
        response = signed_in.post(
            reverse("display-preferences"),
            {"today_group": "calendar", "horizon_days": "14", "next": "/more/"},
        )
        assert response.status_code == 302
        assert response["Location"] == "/more/"
        prefs = agenda.preferences_of(alice)
        assert (prefs.today_group, prefs.horizon_days) == ("calendar", 14)
        assert (prefs.show_overdue, prefs.show_upcoming, prefs.show_season) == (False,) * 3

    def test_preferences_form_does_not_follow_a_foreign_address(self, signed_in: Client) -> None:
        response = signed_in.post(
            reverse("display-preferences"),
            {"today_group": "room", "horizon_days": "7", "next": "https://example.org/"},
        )
        assert response["Location"] == reverse("my-home")
        bad = signed_in.post(
            reverse("display-preferences"), {"today_group": "none", "horizon_days": "7"}
        )
        assert bad.status_code == 200

    @pytest.fixture
    def past(self, alice: User, member: User, alice_home: Home, owner_room: Room) -> Home:
        plumber = services.create_contractor(alice, alice_home, name="Pipes Ltd")
        work = services.create_task(
            alice, alice_home, title="Fix the tap", contractor=plumber, room=owner_room
        )
        services.complete(
            alice, services.open_occurrence_of(work), actual_cost=Decimal("80.50"), note="Washer"
        )
        paint = services.create_task(alice, alice_home, title="Paint the hall")
        services.complete(member, services.open_occurrence_of(paint), actual_cost=Decimal("19.50"))
        gutters = services.create_task(alice, alice_home, title="Clean the gutters")
        services.skip(alice, services.open_occurrence_of(gutters))
        return alice_home

    def test_anonymous_visitors_are_sent_to_sign_in(self, client: Client, alice_home: Home) -> None:
        for address in (
            web("today", alice_home),
            web("history", alice_home),
            reverse("my-home"),
            reverse("display-preferences"),
        ):
            response = client.get(address)
            assert response.status_code == 302, address
            assert "login" in response["Location"], address

    @pytest.mark.parametrize("who", ["bob", "site_admin"])
    def test_a_stranger_and_the_instance_administrator_get_404(
        self, who: str, request: pytest.FixtureRequest, client: Client, busy: Home
    ) -> None:
        client.force_login(request.getfixturevalue(who))
        assert client.get(web("today", busy)).status_code == 404
        assert client.get(web("history", busy)).status_code == 404
        mine = client.get(reverse("my-home")).content.decode()
        assert "Due today" not in mine
        assert busy.name not in mine


class TestApi:
    @pytest.fixture
    def alice_api(self, api_client: APIClient, alice: User) -> APIClient:
        api_client.force_authenticate(alice)
        return api_client

    def test_today(self, alice_api: APIClient, busy: Home) -> None:
        body = alice_api.get(api("home-today", busy)).json()
        assert body["preferences"] == {
            "today_group": "urgency",
            "horizon_days": 7,
            "show_overdue": True,
            "show_upcoming": True,
            "show_season": True,
        }
        assert [s["key"] for s in body["sections"]] == ["overdue", "today", "upcoming", "season"]
        overdue = body["sections"][0]
        assert overdue["title"] == "Overdue"
        assert [o["task_title"] for o in overdue["occurrences"]] == [
            "Late and urgent",
            "Late one",
        ]
        alice_api.patch(api("display-preferences"), {"today_group": "calendar"}, format="json")
        days = alice_api.get(api("home-today", busy)).json()["sections"]
        assert [s["day"] for s in days if s["key"] == "day"] == [
            TODAY.isoformat(),
            (TODAY + 3 * DAY).isoformat(),
        ]

    def test_preferences(self, alice_api: APIClient, api_client: APIClient, bob: User) -> None:
        assert alice_api.get(api("display-preferences")).json()["horizon_days"] == 7
        changed = alice_api.patch(
            api("display-preferences"),
            {"horizon_days": 60, "show_season": False},
            format="json",
        )
        assert changed.status_code == 200
        assert changed.json()["horizon_days"] == 60
        assert changed.json()["show_season"] is False
        assert alice_api.get(api("display-preferences")).json()["horizon_days"] == 60
        assert (
            alice_api.patch(
                api("display-preferences"), {"horizon_days": 5}, format="json"
            ).status_code
            == 400
        )
        api_client.force_authenticate(bob)
        assert api_client.get(api("display-preferences")).json()["horizon_days"] == 7
        assert agenda.preferences_of(bob).horizon_days == 7

    def test_preferences_need_a_person(self, api_client: APIClient) -> None:
        assert api_client.get(api("display-preferences")).status_code in (401, 403)

    def test_my_home(self, alice_api: APIClient, busy: Home, alice: User) -> None:
        second = home_services.create_home(alice, name="Holiday flat")
        body = alice_api.get(api("my-home")).json()
        assert sorted(d["name"] for d in body) == ["Holiday flat", busy.name]
        mine = next(d for d in body if d["home"] == str(busy.id))
        assert [o["task_title"] for o in mine["mine"]] == ["Due today"]
        assert [o["task_title"] for o in mine["overdue"]] == ["Late and urgent", "Late one"]
        only = alice_api.get(api("my-home"), {"home": str(second.id)}).json()
        assert [d["name"] for d in only] == ["Holiday flat"]
        assert alice_api.get(api("my-home"), {"home": str(second.id)[:-1] + "x"}).status_code == 400
        assert (
            alice_api.get(
                api("my-home"), {"home": "00000000-0000-0000-0000-000000000000"}
            ).status_code
            == 404
        )

    def test_my_home_gives_a_stranger_nothing(
        self, api_client: APIClient, bob: User, busy: Home
    ) -> None:
        api_client.force_authenticate(bob)
        assert api_client.get(api("my-home")).json() == []
        assert api_client.get(api("my-home"), {"home": str(busy.id)}).status_code == 404
        assert api_client.get(api("home-today", busy)).status_code == 404

    def test_history_filters_order_and_cost(
        self, alice_api: APIClient, alice: User, member: User, alice_home: Home, owner_room: Room
    ) -> None:
        plumber = services.create_contractor(alice, alice_home, name="Pipes Ltd")
        tap = services.create_task(alice, alice_home, title="Fix the tap", contractor=plumber)
        services.complete(
            alice,
            services.open_occurrence_of(tap),
            on=TODAY - 12 * DAY,
            actual_cost=Decimal("80.50"),
            note="Washer",
        )
        paint = services.create_task(alice, alice_home, title="Paint the hall")
        services.complete(member, services.open_occurrence_of(paint), actual_cost=Decimal("19.50"))
        skipped = services.create_task(alice, alice_home, title="Clean the gutters")
        services.skip(alice, services.open_occurrence_of(skipped))
        listing = api("home-occurrence-list", alice_home)
        titles_of = lambda **q: [  # noqa: E731
            o["task_title"] for o in alice_api.get(listing, q).json()["results"]
        ]
        assert titles_of(status="closed", ordering="recent") == [
            "Clean the gutters",
            "Paint the hall",
            "Fix the tap",
        ]
        assert titles_of(status="closed", contractor=str(plumber.id)) == ["Fix the tap"]
        assert titles_of(status="closed", completed_by=str(member.id)) == ["Paint the hall"]
        assert titles_of(status="closed", q="washer") == ["Fix the tap"]
        assert titles_of(status="closed", q="PAINT") == ["Paint the hall"]
        assert titles_of(status="closed", closed_after=(TODAY - DAY).isoformat()) == [
            "Paint the hall",
            "Clean the gutters",
        ] or titles_of(status="closed", closed_after=(TODAY - DAY).isoformat()) == [
            "Clean the gutters",
            "Paint the hall",
        ]
        assert titles_of(status="closed", closed_before=(TODAY - 5 * DAY).isoformat()) == [
            "Fix the tap"
        ]
        assert alice_api.get(listing, {"closed_after": "yesterday"}).status_code == 400
        cost = alice_api.get(api("home-occurrence-cost", alice_home), {"status": "closed"}).json()
        assert cost == {"total": "100.00", "with_cost": 2, "count": 3}
        some = alice_api.get(
            api("home-occurrence-cost", alice_home), {"status": "closed", "q": "paint"}
        ).json()
        assert some == {"total": "19.50", "with_cost": 1, "count": 1}

    def test_history_pages_by_cursor_in_the_recent_order(
        self, alice_api: APIClient, alice: User, alice_home: Home
    ) -> None:
        for number in range(5):
            task = services.create_task(alice, alice_home, title=f"Chore {number}")
            services.complete(alice, services.open_occurrence_of(task), on=TODAY - number * DAY)
        listing = api("home-occurrence-list", alice_home)
        first = alice_api.get(
            listing, {"status": "closed", "ordering": "recent", "page_size": 2}
        ).json()
        assert [o["task_title"] for o in first["results"]] == ["Chore 0", "Chore 1"]
        second = alice_api.get(first["next"]).json()
        assert [o["task_title"] for o in second["results"]] == ["Chore 2", "Chore 3"]

    def test_scopes_of_a_token(self, alice: User, alice_home: Home, busy: Home) -> None:
        def client(scopes: list[str]) -> APIClient:
            _token, raw = token_services.issue_token(
                alice, name="t", scopes=scopes, homes=[alice_home], lifetime=timedelta(days=1)
            )
            found = APIClient()
            found.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
            return found

        reading = client(["read"])
        for address in (
            api("home-today", alice_home),
            api("my-home"),
            api("display-preferences"),
            api("home-occurrence-cost", alice_home),
        ):
            assert reading.get(address).status_code == 200, address
        assert (
            reading.patch(
                api("display-preferences"), {"show_season": False}, format="json"
            ).status_code
            == 403
        )
        writing = client(["write"])
        assert (
            writing.patch(
                api("display-preferences"), {"show_season": False}, format="json"
            ).status_code
            == 200
        )
        assert writing.get(api("home-today", alice_home)).status_code == 403
        assert client(["events"]).get(api("my-home")).status_code == 403

    def test_a_token_bound_to_another_home_sees_nothing(
        self, alice: User, alice_home: Home, busy: Home
    ) -> None:
        second = home_services.create_home(alice, name="Holiday flat")
        _token, raw = token_services.issue_token(
            alice, name="t", scopes=["read"], homes=[second], lifetime=timedelta(days=1)
        )
        found = APIClient()
        found.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert found.get(api("home-today", alice_home)).status_code == 404
        assert found.get(api("home-occurrence-cost", alice_home)).status_code == 404
        assert [d["name"] for d in found.get(api("my-home")).json()] == ["Holiday flat"]


def test_open_tasks_total_matches_the_models(busy: Home) -> None:
    """A guard on the fixture itself: eight tasks, eight open occurrences."""
    assert Task.objects.filter(home=busy).count() == 8
    assert Occurrence.objects.filter(home=busy, status="planned").count() == 8
    assert isinstance(TODAY, datetime.date)
