"""The tabs of the areas of the application: one component, the current tab marked."""

import re
from collections.abc import Callable

import pytest
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes.models import Home

pytest_plugins = ("tests.rooms_fixtures",)

pytestmark = pytest.mark.django_db


def tabs_of(html: str) -> list[tuple[str, bool]]:
    """(label, current) of the links of the tab list, in order."""
    block = re.search(r'<nav class="tabs".*?</nav>', html, re.S)
    assert block, "no tab bar"
    return [
        (label, "aria-current" in attrs)
        for attrs, label in re.findall(r'<a class="tab" href="[^"]*"([^>]*)>([^<]*)</a>', block[0])
    ]


def current(html: str) -> list[str]:
    return [label for label, here in tabs_of(html) if here]


class TestTaskTabs:
    def test_every_screen_of_the_tasks_marks_its_tab(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        for view, label in [
            ("today", "Today"),
            ("list", "All tasks"),
            ("history", "History"),
        ]:
            page = signed_in.get(reverse(f"tasks:{view}", kwargs={"home_id": alice_home.id}))
            html = page.content.decode()
            assert [t for t, _ in tabs_of(html)] == [
                "Today",
                "All tasks",
                "History",
                "Display preferences",
            ]
            assert current(html) == [label]

    def test_the_preferences_keep_the_tabs_of_the_home_they_came_from(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        today = reverse("tasks:today", kwargs={"home_id": alice_home.id})
        html = signed_in.get(reverse("display-preferences"), {"next": today}).content.decode()
        assert current(html) == ["Display preferences"]
        assert today in html

    def test_no_tabs_without_a_home(self, signed_in: Client) -> None:
        html = signed_in.get(reverse("display-preferences")).content.decode()
        assert 'class="tabs"' not in html

    def test_a_home_the_person_cannot_open_gives_no_tabs(
        self, signed_in: Client, bob_home: Home
    ) -> None:
        stranger = reverse("tasks:today", kwargs={"home_id": bob_home.id})
        html = signed_in.get(reverse("display-preferences"), {"next": stranger}).content.decode()
        assert 'class="tabs"' not in html

    def test_an_address_outside_the_application_gives_no_tabs(self, signed_in: Client) -> None:
        html = signed_in.get(
            reverse("display-preferences"), {"next": "https://example.com/x"}
        ).content.decode()
        assert 'class="tabs"' not in html

    def test_a_tab_is_a_real_link_for_the_keyboard(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        html = signed_in.get(
            reverse("tasks:today", kwargs={"home_id": alice_home.id})
        ).content.decode()
        assert '<nav class="tabs" aria-label="Tasks">' in html


class TestHomeTabs:
    def test_an_owner_sees_the_overview_household_and_audit(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        for view, label in [
            ("homes:detail", "Overview"),
            ("homes:household", "Household and roles"),
            ("homes:audit", "Audit log"),
        ]:
            html = signed_in.get(reverse(view, kwargs={"home_id": alice_home.id})).content.decode()
            assert [t for t, _ in tabs_of(html)] == ["Overview", "Household and roles", "Audit log"]
            assert current(html) == [label]

    def test_a_member_has_no_audit_tab(
        self, client: Client, alice_home: Home, member: User
    ) -> None:
        client.force_login(member)
        html = client.get(
            reverse("homes:household", kwargs={"home_id": alice_home.id})
        ).content.decode()
        assert [t for t, _ in tabs_of(html)] == ["Overview", "Household and roles"]

    def test_a_member_page_keeps_the_household_tab_current(
        self, signed_in: Client, alice_home: Home, member: User
    ) -> None:
        membership = alice_home.memberships.get(user=member)
        html = signed_in.get(
            reverse("homes:member", kwargs={"home_id": alice_home.id, "member_id": membership.id})
        ).content.decode()
        assert current(html) == ["Household and roles"]


class TestInstanceTabs:
    @pytest.fixture
    def admin(self, make_user: Callable[..., User], client: Client) -> Client:
        client.force_login(make_user("admin@example.com", is_staff=True, is_superuser=True))
        return client

    def test_each_page_of_the_administration_marks_its_tab(self, admin: Client) -> None:
        for view, label in [
            ("instance:overview", "Overview"),
            ("instance:settings", "Settings"),
            ("instance:providers", "Sign-in providers"),
            ("instance:usage", "Files of the homes"),
            ("instance:audit", "Audit log"),
        ]:
            html = admin.get(reverse(view)).content.decode()
            assert [t for t, _ in tabs_of(html)] == [
                "Overview",
                "Settings",
                "Sign-in providers",
                "Files of the homes",
                "Audit log",
            ]
            assert current(html) == [label]
