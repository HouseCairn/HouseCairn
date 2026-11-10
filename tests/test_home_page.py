"""One home for the application: Today, and Report a problem from it (NAV-04, NAV-07)."""

import json
import re
from collections.abc import Callable

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.reports import services as report_services
from tests.conftest import PASSWORD

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = pytest.mark.django_db


def today(home: Home) -> str:
    return reverse("tasks:today", kwargs={"home_id": home.id})


def report_link(home: Home, page: str) -> str:
    return f"{reverse('reports:create', kwargs={'home_id': home.id})}?next={page}"


@pytest.fixture
def second_home(alice: User) -> Home:
    return home_services.create_home(alice, name="Holiday flat")


class TestTheStartPage:
    def test_one_home_opens_on_today(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.get(reverse("index"))
        assert response.status_code == 302
        assert response["Location"] == today(alice_home)

    def test_several_homes_open_on_today_of_all_of_them(
        self, signed_in: Client, alice_home: Home, second_home: Home
    ) -> None:
        response = signed_in.get(reverse("index"))
        assert response.status_code == 200
        html = response.content.decode()
        assert "<h1>Today</h1>" in html
        assert "My home<" not in html
        assert today(alice_home) in html
        assert today(second_home) in html

    def test_several_homes_have_no_row_of_tabs_with_the_same_name(
        self, signed_in: Client, alice_home: Home, second_home: Home
    ) -> None:
        html = signed_in.get(reverse("index")).content.decode()
        labels = re.findall(r'<nav class="tabs[^"]*" aria-label="([^"]*)"', html)
        assert len(labels) == len(set(labels))

    def test_an_account_with_no_home_gets_the_welcome(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        client.force_login(make_user("alone@example.com"))
        response = client.get(reverse("index"))
        assert response.status_code == 200
        html = response.content.decode()
        assert "Welcome" in html
        assert reverse("homes:create") in html

    def test_a_visitor_gets_the_welcome(self, client: Client) -> None:
        response = client.get(reverse("index"))
        assert response.status_code == 200
        assert reverse("account_login") in response.content.decode()

    def test_the_old_address_of_my_home_redirects(
        self, signed_in: Client, alice_home: Home, second_home: Home
    ) -> None:
        response = signed_in.get(reverse("my-home"), {"home": str(second_home.id)})
        assert response.status_code == 302
        assert response["Location"] == f"{reverse('index')}?home={second_home.id}"
        shown = signed_in.get(response["Location"]).content.decode()
        assert "Holiday flat" in shown

    def test_the_old_address_is_for_everyone_even_a_visitor(self, client: Client) -> None:
        response = client.get(reverse("my-home"))
        assert response.status_code == 302
        assert response["Location"] == reverse("index")

    def test_the_selector_stays_on_the_home_page(
        self, signed_in: Client, alice_home: Home, second_home: Home
    ) -> None:
        html = signed_in.get(reverse("index")).content.decode()
        assert 'name="home"' in html
        assert "action=" not in html.split('name="home"')[0].rsplit("<form", 1)[1]


class TestEveryDoorLeadsToToday:
    def test_signing_in_lands_on_today(self, client: Client, alice: User, alice_home: Home) -> None:
        response = client.post(
            reverse("account_login"), {"login": alice.email, "password": PASSWORD}
        )
        assert response["Location"] == reverse("index")
        assert client.get(response["Location"])["Location"] == today(alice_home)

    def test_the_manifest_starts_on_the_home_page(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        manifest = json.loads(signed_in.get(reverse("manifest")).content)
        assert manifest["start_url"] == reverse("index")
        assert signed_in.get(manifest["start_url"])["Location"] == today(alice_home)

    def test_the_logo_leads_to_the_home_page(self, signed_in: Client, alice_home: Home) -> None:
        html = signed_in.get(today(alice_home)).content.decode()
        brand = re.search(r'<a class="brand[^"]*" href="([^"]*)"', html)
        assert brand is not None
        assert brand.group(1) == reverse("index")

    def test_the_today_entry_outside_a_home_is_the_home_page(self, signed_in: Client) -> None:
        html = signed_in.get(reverse("more")).content.decode()
        entry = re.search(r'<a class="nav-link" href="([^"]*)"[^>]*>\s*<svg', html)
        assert entry is not None
        assert entry.group(1) == reverse("index")

    def test_the_preferences_come_back_to_the_home_page(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        response = signed_in.post(
            reverse("display-preferences"), {"today_group": "room", "horizon_days": "7"}
        )
        assert response["Location"] == reverse("index")


@pytest.mark.parametrize("who", ["alice", "member", "reader"])
class TestReportFromToday:
    def test_every_role_has_the_button(
        self, who: str, request: pytest.FixtureRequest, client: Client, alice_home: Home
    ) -> None:
        client.force_login(request.getfixturevalue(who))
        page = today(alice_home)
        html = client.get(page).content.decode()
        assert "Report a problem" in html
        assert report_link(alice_home, page) in html.replace("&amp;", "&").replace("%2F", "/")

    def test_the_button_opens_the_form_in_one_tap(
        self, who: str, request: pytest.FixtureRequest, client: Client, alice_home: Home
    ) -> None:
        client.force_login(request.getfixturevalue(who))
        form = client.get(reverse("reports:create", kwargs={"home_id": alice_home.id}))
        assert form.status_code == 200
        assert 'name="title"' in form.content.decode()


def test_the_several_homes_page_offers_the_button_for_each_home(
    signed_in: Client, alice_home: Home, second_home: Home
) -> None:
    html = signed_in.get(reverse("index")).content.decode()
    for home in (alice_home, second_home):
        assert reverse("reports:create", kwargs={"home_id": home.id}) in html


def test_a_stranger_has_no_button_on_a_home_that_is_not_theirs(
    client: Client, bob: User, alice_home: Home
) -> None:
    client.force_login(bob)
    assert client.get(today(alice_home)).status_code == 404


class TestReportsCount:
    def count_queries(self, client: Client, url: str) -> tuple[str, int]:
        with CaptureQueriesContext(connection) as queries:
            html = client.get(url).content.decode()
        reports = [q for q in queries.captured_queries if 'FROM "reports_report"' in q["sql"]]
        return html, len(reports)

    def test_the_column_and_more_show_the_count_to_who_may_write(
        self, signed_in: Client, alice: User, reader: User, alice_home: Home
    ) -> None:
        report_services.create_report(reader, alice_home, title="The tap drips")
        report_services.create_report(reader, alice_home, title="The door sticks")
        html, _ = self.count_queries(signed_in, today(alice_home))
        assert "Reports (2)" in html
        elsewhere = reverse("tasks:list", kwargs={"home_id": alice_home.id})
        html, _ = self.count_queries(signed_in, elsewhere)
        assert "Reports (2)" in html

    def test_a_reader_sees_no_count(self, client: Client, reader: User, alice_home: Home) -> None:
        report_services.create_report(reader, alice_home, title="The tap drips")
        client.force_login(reader)
        html, _ = self.count_queries(client, today(alice_home))
        assert "Reports (" not in html

    def test_no_count_when_nothing_waits(self, signed_in: Client, alice_home: Home) -> None:
        html, _ = self.count_queries(signed_in, today(alice_home))
        assert "Reports (" not in html

    def test_the_page_reads_the_reports_once(
        self, signed_in: Client, reader: User, alice_home: Home
    ) -> None:
        report_services.create_report(reader, alice_home, title="The tap drips")
        # The line of Today and the entry of the column share one query.
        _, on_today = self.count_queries(signed_in, today(alice_home))
        assert on_today == 1
        _, elsewhere = self.count_queries(
            signed_in, reverse("rooms:list", kwargs={"home_id": alice_home.id})
        )
        assert elsewhere == 1
        _, on_more = self.count_queries(signed_in, reverse("more"))
        assert on_more == 1
