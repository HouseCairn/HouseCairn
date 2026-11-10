"""The current home: remembered, chosen in the app bar, never a permission (NAV-08, NAV-16).

docs/developer/design-guide.md, "Current home".
"""

import re
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.apitokens.models import Scope
from housecairn.homes import current
from housecairn.homes import services as home_services
from housecairn.homes.models import Home, Membership, Role
from housecairn.projects import services as project_services
from housecairn.rooms.models import Room
from housecairn.tasks import services as task_services

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = pytest.mark.django_db

# The roots each entry of the navigation opens in a home.
ENTRIES = {
    "rooms": "rooms:list",
    "tasks": "tasks:list",
    "stock": "stock:list",
    "projects": "projects:list",
    "budget": "budget:overview",
}


def root(route: str, home: Home) -> str:
    return reverse(route, kwargs={"home_id": home.id})


def switch(client: Client, value: object, next_url: str = "") -> str:
    data = {"home": str(value)}
    if next_url:
        data["next"] = next_url
    response = client.post(reverse("homes:current"), data)
    assert response.status_code == 302, response.status_code
    return str(response["Location"])


def selector(html: str) -> str | None:
    found = re.search(r'<details class="home-switcher">.*?</details>', html, re.S)
    return found.group(0) if found else None


@pytest.fixture
def flat(alice: User) -> Home:
    """A second home of Alice, after the first one by name ("Flat" < "Main house")."""
    return home_services.create_home(alice, name="Seaside flat")


@pytest.fixture
def strangers(bob: User) -> Home:
    return home_services.create_home(bob, name="Bob's house")


class TestOneHome:
    def test_no_selector(self, signed_in: Client, alice_home: Home) -> None:
        html = signed_in.get(root("tasks:today", alice_home)).content.decode()
        assert selector(html) is None
        assert reverse("homes:current") not in html

    @pytest.mark.parametrize("entry", ENTRIES)
    def test_every_entry_opens_the_home(
        self, signed_in: Client, alice_home: Home, entry: str
    ) -> None:
        response = signed_in.get(reverse(entry))
        assert response["Location"] == root(ENTRIES[entry], alice_home)

    def test_all_homes_is_refused(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.post(reverse("homes:current"), {"home": "all"})
        assert response.status_code == 404


class TestTwoHomes:
    def test_the_selector_lists_both_homes_and_posts_with_csrf(
        self, signed_in: Client, alice_home: Home, flat: Home
    ) -> None:
        html = signed_in.get(root("rooms:list", alice_home)).content.decode()
        found = selector(html)
        assert found is not None
        assert 'method="post"' in found
        assert 'name="csrfmiddlewaretoken"' in found
        assert f'value="{alice_home.id}" class="home-switcher-choice" aria-current="true"' in found
        assert f'value="{flat.id}"' in found
        assert "Seaside flat" in found
        # "All homes" belongs to Today only.
        assert 'value="all"' not in found

    def test_the_switch_needs_the_csrf_token(
        self, alice: User, alice_home: Home, flat: Home
    ) -> None:
        client = Client(enforce_csrf_checks=True)
        client.force_login(alice)
        response = client.post(reverse("homes:current"), {"home": str(flat.id)})
        assert response.status_code == 403

    def test_the_switch_is_a_post(self, signed_in: Client, alice_home: Home, flat: Home) -> None:
        response = signed_in.get(reverse("homes:current"), {"home": str(flat.id)})
        assert response.status_code == 405

    @pytest.mark.parametrize("entry", ENTRIES)
    def test_every_entry_opens_the_current_home_without_asking(
        self, signed_in: Client, alice_home: Home, flat: Home, entry: str
    ) -> None:
        # Before any choice, the first home by name.
        assert signed_in.get(reverse(entry))["Location"] == root(ENTRIES[entry], alice_home)
        switch(signed_in, flat.id)
        assert signed_in.get(reverse(entry))["Location"] == root(ENTRIES[entry], flat)

    def test_the_switch_opens_the_same_screen_in_the_other_home(
        self, signed_in: Client, alice_home: Home, flat: Home
    ) -> None:
        target = switch(signed_in, flat.id, root("stock:list", alice_home))
        assert target == root("stock:list", flat)

    def test_a_record_of_the_previous_home_opens_its_section_root(
        self, signed_in: Client, alice: User, alice_home: Home, flat: Home
    ) -> None:
        task = task_services.create_task(alice, alice_home, title="Bleed the radiators")
        page = reverse("tasks:detail", kwargs={"home_id": alice_home.id, "task_id": task.id})
        assert switch(signed_in, flat.id, page) == root("tasks:today", flat)

    def test_a_page_of_a_home_makes_it_current(
        self, signed_in: Client, alice_home: Home, flat: Home
    ) -> None:
        signed_in.get(root("projects:list", flat))
        assert signed_in.get(reverse("rooms"))["Location"] == root("rooms:list", flat)
        html = signed_in.get(reverse("more")).content.decode()
        found = selector(html)
        assert found is not None
        assert '<span class="home-switcher-name">Seaside flat</span>' in found

    def test_today_offers_all_homes(self, signed_in: Client, alice_home: Home, flat: Home) -> None:
        html = signed_in.get(root("tasks:today", alice_home)).content.decode()
        found = selector(html)
        assert found is not None
        assert 'value="all"' in found
        assert switch(signed_in, "all", root("tasks:today", alice_home)) == reverse("index")
        html = signed_in.get(reverse("index")).content.decode()
        found = selector(html)
        assert found is not None
        assert '<span class="home-switcher-name">All homes</span>' in found
        # Choosing one home again: Today opens on it.
        switch(signed_in, alice_home.id, reverse("index"))
        assert signed_in.get(reverse("index"))["Location"] == root("tasks:today", alice_home)

    def test_all_homes_does_not_change_the_other_sections(
        self, signed_in: Client, alice_home: Home, flat: Home
    ) -> None:
        switch(signed_in, flat.id)
        switch(signed_in, "all")
        assert signed_in.get(reverse("rooms"))["Location"] == root("rooms:list", flat)
        # Opening a task of one home from the page of all homes keeps "All homes" for Today.
        signed_in.get(root("tasks:today", alice_home))
        assert signed_in.get(reverse("index")).status_code == 200


class TestAllHomesOnToday:
    def test_each_row_names_its_home(
        self, signed_in: Client, alice: User, alice_home: Home, flat: Home
    ) -> None:
        task_services.create_task(
            alice,
            alice_home,
            title="Clean the gutters",
            due_on=task_services.today(),
            assignee=alice,
        )
        task_services.create_task(
            alice, flat, title="Air the bedrooms", due_on=task_services.today(), assignee=alice
        )
        html = signed_in.get(reverse("index")).content.decode()
        rows = re.findall(r'<li class="task-row[^"]*">.*?</li>', html, re.S)
        gutters = next(r for r in rows if "Clean the gutters" in r)
        bedrooms = next(r for r in rows if "Air the bedrooms" in r)
        assert "Main house" in gutters
        assert "Seaside flat" in bedrooms

    def test_it_has_the_tabs_of_today(
        self, signed_in: Client, alice_home: Home, flat: Home
    ) -> None:
        html = signed_in.get(reverse("index")).content.decode()
        assert f'href="{reverse("calendar:week")}"' in html
        assert re.search(rf'href="{reverse("index")}"[^>]*aria-current="page"', html)


class TestIsolation:
    def test_a_forged_session_opens_nothing_of_another_home(
        self, signed_in: Client, alice_home: Home, strangers: Home
    ) -> None:
        session = signed_in.session
        session[current.HOME_KEY] = str(strangers.id)
        session.save()
        for entry, route in ENTRIES.items():
            assert signed_in.get(reverse(entry))["Location"] == root(route, alice_home)
        html = signed_in.get(reverse("calendar:week")).content.decode()
        assert "Bob's house" not in html
        assert signed_in.session.get(current.HOME_KEY) != str(strangers.id)

    @pytest.mark.parametrize("entry", ["rooms", "budget", "calendar:week"])
    def test_a_forged_session_shows_nothing_of_another_home_in_a_section(
        self, signed_in: Client, alice_home: Home, bob: User, strangers: Home, entry: str
    ) -> None:
        Room.objects.create(home=strangers, name="Bob's secret room", position=0)
        project_services.create_project(
            bob, strangers, title="Bob's secret project", budget=Decimal("900")
        )
        task_services.create_task(
            bob, strangers, title="Bob's secret task", due_on=task_services.today()
        )
        session = signed_in.session
        session[current.HOME_KEY] = str(strangers.id)
        session.save()
        response = signed_in.get(reverse(entry), follow=True)
        assert response.status_code == 200
        html = response.content.decode()
        assert "Bob" not in html
        assert str(strangers.id) not in html
        assert str(strangers.id) not in " ".join(url for url, _ in response.redirect_chain)
        # The forged value is dropped; the first open home by name stands in for it.
        assert signed_in.session.get(current.HOME_KEY) != str(strangers.id)
        if entry != "calendar:week":
            assert response.redirect_chain[-1][0].startswith(
                reverse(ENTRIES[entry], kwargs={"home_id": alice_home.id})
            )

    def test_a_forged_choice_answers_404(
        self, signed_in: Client, alice_home: Home, flat: Home, strangers: Home
    ) -> None:
        for value in (strangers.id, "not-a-uuid", ""):
            response = signed_in.post(reverse("homes:current"), {"home": str(value)})
            assert response.status_code == 404
        assert signed_in.session.get(current.HOME_KEY) != str(strangers.id)

    def test_a_forged_address_answers_404_and_changes_nothing(
        self, signed_in: Client, alice_home: Home, flat: Home, strangers: Home
    ) -> None:
        switch(signed_in, flat.id)
        assert signed_in.get(root("rooms:list", strangers)).status_code == 404
        assert signed_in.get(reverse("calendar:week"), {"home": strangers.id}).status_code == 404
        assert signed_in.get(reverse("rooms"))["Location"] == root("rooms:list", flat)

    def test_a_home_left_falls_back_to_another(
        self, client: Client, alice: User, bob: User, alice_home: Home, strangers: Home
    ) -> None:
        Membership.objects.create(home=strangers, user=alice, role=Role.MEMBER)
        client.force_login(alice)
        switch(client, strangers.id)
        assert client.get(reverse("rooms"))["Location"] == root("rooms:list", strangers)
        home_services.leave_home(alice, strangers)
        assert client.get(reverse("rooms"))["Location"] == root("rooms:list", alice_home)
        assert client.session.get(current.HOME_KEY) is None
        # One home left: no selector, and Today opens on it.
        assert selector(client.get(reverse("more")).content.decode()) is None
        assert client.get(reverse("index"))["Location"] == root("tasks:today", alice_home)

    def test_a_home_deleted_falls_back_to_another(
        self, signed_in: Client, alice: User, alice_home: Home, flat: Home
    ) -> None:
        switch(signed_in, flat.id)
        home_services.delete_home(alice, flat, confirmation=flat.name)
        assert signed_in.get(reverse("projects"))["Location"] == root("projects:list", alice_home)

    def test_the_last_home_deleted_leads_to_the_page_without_a_home(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        signed_in.get(root("rooms:list", alice_home))
        home_services.delete_home(alice, alice_home, confirmation=alice_home.name)
        for entry in ENTRIES:
            page = signed_in.get(reverse(entry))
            assert page.status_code == 200
            assert reverse("homes:create") in page.content.decode()
        assert "Welcome" in signed_in.get(reverse("index")).content.decode()


class TestCalendar:
    def test_it_shows_the_current_home_and_its_tabs(
        self, signed_in: Client, alice: User, alice_home: Home, flat: Home
    ) -> None:
        task_services.create_task(
            alice, alice_home, title="Clean the gutters", due_on=task_services.today()
        )
        task_services.create_task(
            alice, flat, title="Air the bedrooms", due_on=task_services.today()
        )
        switch(signed_in, flat.id)
        html = signed_in.get(reverse("calendar:week")).content.decode()
        assert "Air the bedrooms" in html
        assert "Clean the gutters" not in html
        # Its way back: the tabs of Today, in the current home.
        assert f'href="{root("tasks:today", flat)}"' in html
        assert f'href="{root("tasks:list", flat)}"' in html

    def test_all_homes_shows_every_home_with_a_way_back(
        self, signed_in: Client, alice: User, alice_home: Home, flat: Home
    ) -> None:
        task_services.create_task(
            alice, alice_home, title="Clean the gutters", due_on=task_services.today()
        )
        task_services.create_task(
            alice, flat, title="Air the bedrooms", due_on=task_services.today()
        )
        switch(signed_in, "all")
        html = signed_in.get(reverse("calendar:week")).content.decode()
        assert "Air the bedrooms" in html
        assert "Clean the gutters" in html
        assert re.search(rf'<a[^>]*href="{reverse("index")}"[^>]*>\s*Today', html)

    def test_the_switch_from_the_calendar_comes_back_to_it(
        self, signed_in: Client, alice_home: Home, flat: Home
    ) -> None:
        page = f"{reverse('calendar:month')}?home={alice_home.id}&date=2026-01-05"
        assert switch(signed_in, flat.id, page) == f"{reverse('calendar:month')}?date=2026-01-05"


class TestApiTokens:
    def test_a_token_sees_its_homes_and_no_session_is_written(
        self, api_client: APIClient, alice: User, alice_home: Home, flat: Home
    ) -> None:
        _token, raw = token_services.issue_token(
            alice, name="test", scopes=[Scope.READ], homes=[flat]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        response = api_client.get(reverse("api-v1:home-list"))
        assert response.status_code == 200
        body = response.json()
        rows = body["results"] if isinstance(body, dict) else body
        assert [row["id"] for row in rows] == [str(flat.id)]
        rooms = api_client.get(reverse("api-v1:home-room-list", kwargs={"home_id": alice_home.id}))
        assert rooms.status_code == 404
        assert "sessionid" not in response.cookies


class TestReviewRemarks:
    def test_a_reader_waits_for_no_report_without_a_query(
        self, reader: User, alice_home: Home, rf: object
    ) -> None:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from housecairn.reports.services import waiting_for

        request = rf.get("/more/")  # type: ignore[attr-defined]
        request.user = reader
        request.session = {}
        current.for_request(request)
        with CaptureQueriesContext(connection) as queries:
            assert waiting_for(request, alice_home.id) == 0
        assert len(queries) == 0

    def test_the_back_link_to_the_root_names_the_welcome_page_without_a_home(
        self, rf: object, make_user: object, alice: User, alice_home: Home
    ) -> None:
        from housecairn.core import navigation

        request = rf.get("/more/")  # type: ignore[attr-defined]
        request.session = {}
        request.user = make_user("alone@example.com")  # type: ignore[operator]
        assert navigation.label_for("/", request) == "Welcome"
        request = rf.get("/more/")  # type: ignore[attr-defined]
        request.session = {}
        request.user = alice
        assert navigation.label_for("/", request) == "Today"

    def test_without_script_the_focus_keeps_the_room_of_the_longest_banner(self) -> None:
        from pathlib import Path

        css = Path("src/housecairn/static/css/no-script.css").read_text()
        rule = re.search(r"html:has\(\.undo-region \.undo-banner\) \{([^}]*)\}", css)
        assert rule is not None
        assert "scroll-padding-bottom" in rule.group(1)
        assert "9rem" in rule.group(1)
