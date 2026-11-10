"""The application served under a path prefix (core/prefix.py, docs/adr/0055).

The prefix is the one of Home Assistant's Ingress, which starts like the API of the
application (`/api/...`): a route that only looked at the start of the path would mix them.
The settings are those `settings.py` computes from `HOUSECAIRN_URL_PREFIX`, read by running
it with the variable set. The proxy may pass the path with the prefix (`reverse` gives it)
or without it: both are covered.
"""

import datetime
import json
import os
import re
import runpy
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock
from urllib.parse import quote

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, RequestFactory
from django.urls import reverse, set_script_prefix
from icalendar import Calendar
from pytest_django.fixtures import Settings as SettingsWrapper

from housecairn.accounts.models import User
from housecairn.calendar import feeds, ics
from housecairn.core import navigation
from housecairn.core.prefix import in_application, parse_header_name, parse_prefix
from housecairn.homes import emails as home_emails
from housecairn.homes.models import Home
from housecairn.labels import services as label_services
from housecairn.rooms.models import Item, Room
from housecairn.tasks import services
from housecairn.tasks.models import Task
from tests.conftest import PASSWORD

pytest_plugins = ("tests.rooms_fixtures", "tests.tasks_fixtures")

pytestmark = pytest.mark.django_db

PREFIX = "/api/hassio_ingress/0123abcdEF-_x"
SRC = Path(__file__).resolve().parents[1] / "src" / "housecairn"

# The settings that follow the prefix, as settings.py computes them.
FOLLOWING = (
    "HOUSECAIRN_URL_PREFIX",
    "FORCE_SCRIPT_NAME",
    "SESSION_COOKIE_PATH",
    "CSRF_COOKIE_PATH",
    "LANGUAGE_COOKIE_PATH",
    "SECURE_REDIRECT_EXEMPT",
)

TASK_FORM = {
    "title": "Bleed the radiators",
    "priority": "normal",
    "repeat_mode": "once",
    "repeat_interval": "1",
    "repeat_unit": "month",
    "hide_days_before": "0",
}


def computed_settings(**variables: str) -> dict[str, Any]:
    """The module-level names of settings.py, run with these environment variables."""
    with mock.patch.dict(os.environ, variables):
        return runpy.run_path(str(SRC / "settings.py"))


@pytest.fixture(scope="module")
def prefixed_values() -> dict[str, Any]:
    found = computed_settings(HOUSECAIRN_URL_PREFIX=PREFIX + "/")
    # A name settings.py does not define keeps its value: the variable is then ignored.
    return {name: found[name] for name in FOLLOWING if name in found}


@pytest.fixture
def prefixed(settings: SettingsWrapper, prefixed_values: dict[str, Any]) -> Iterator[str]:
    for name, value in prefixed_values.items():
        setattr(settings, name, value)
    # What django.setup() does in the web process and the task worker.
    set_script_prefix((settings.FORCE_SCRIPT_NAME or "") + "/")
    yield PREFIX
    set_script_prefix("/")


@pytest.fixture
def header_mode(settings: SettingsWrapper) -> Iterator[None]:
    """No prefix of its own; a trusted proxy gives it in X-Ingress-Path."""
    settings.HOUSECAIRN_URL_PREFIX_HEADER = "X-Ingress-Path"
    yield
    set_script_prefix("/")


@pytest.fixture
def signed_in(client: Client, alice: User, prefixed: str) -> Client:
    client.force_login(alice)
    return client


class _Addresses(HTMLParser):
    """Every address a page links to, loads or sends to."""

    NAMES = {"href", "src", "action", "formaction", "poster", "content"}

    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value and (
                name in self.NAMES or name.startswith("hx-") or name.endswith(("-url", "url"))
            ):
                self.found.append(value)

    handle_startendtag = handle_starttag


def outside(html: str) -> list[str]:
    """The addresses of the page that start at the root of the site, outside the prefix."""
    scanner = _Addresses()
    scanner.feed(html)
    return [
        value
        for value in scanner.found
        if value.startswith("/") and not value.startswith(PREFIX + "/") and value != PREFIX
    ]


# ---------- the variables ----------


class TestVariables:
    def test_settings_follow_the_prefix(self, prefixed_values: dict[str, Any]) -> None:
        assert set(prefixed_values) == set(FOLLOWING)
        assert prefixed_values["HOUSECAIRN_URL_PREFIX"] == PREFIX
        assert prefixed_values["FORCE_SCRIPT_NAME"] == PREFIX
        assert prefixed_values["SESSION_COOKIE_PATH"] == PREFIX
        assert prefixed_values["CSRF_COOKIE_PATH"] == PREFIX
        assert prefixed_values["LANGUAGE_COOKIE_PATH"] == PREFIX
        [exempt] = prefixed_values["SECURE_REDIRECT_EXEMPT"]
        assert re.search(exempt, PREFIX[1:] + "/healthz")
        assert not re.search(exempt, "healthz")

    def test_without_the_variable_nothing_moves(self) -> None:
        found = computed_settings(HOUSECAIRN_URL_PREFIX="")
        assert found["FORCE_SCRIPT_NAME"] is None
        assert found["SESSION_COOKIE_PATH"] == found["CSRF_COOKIE_PATH"] == "/"
        assert found["SECURE_REDIRECT_EXEMPT"] == [r"^healthz$"]
        assert found["HOUSECAIRN_URL_PREFIX_HEADER"] == ""

    @pytest.mark.parametrize("value", ["housecairn", "/a//b", "/a/../b", "/a b", "/a?b", "//x"])
    def test_a_prefix_that_is_not_a_plain_path_is_refused(self, value: str) -> None:
        with pytest.raises(ImproperlyConfigured):
            parse_prefix(value)

    def test_a_header_name_is_a_name(self) -> None:
        assert parse_header_name(" X-Ingress-Path ") == "X-Ingress-Path"
        with pytest.raises(ImproperlyConfigured):
            parse_header_name("X-Ingress-Path: /x")


# ---------- the journeys, under the prefix ----------


class TestSignIn:
    def test_sign_in_with_csrf_checks_lands_under_the_prefix(
        self, alice: User, prefixed: str
    ) -> None:
        client = Client(enforce_csrf_checks=True)
        login = reverse("account_login")
        assert login.startswith(PREFIX + "/")
        page = client.get(login)
        assert page.status_code == 200
        assert outside(page.content.decode()) == []
        assert client.cookies["csrftoken"]["path"] == PREFIX
        response = client.post(
            login,
            {
                "login": alice.email,
                "password": PASSWORD,
                "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
            },
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("index") == PREFIX + "/"
        assert response.cookies["sessionid"]["path"] == PREFIX

    def test_a_next_under_the_prefix_is_followed(
        self, client: Client, alice: User, prefixed: str
    ) -> None:
        target = reverse("rooms")
        assert target.startswith(PREFIX + "/")
        response = client.post(
            reverse("account_login"), {"login": alice.email, "password": PASSWORD, "next": target}
        )
        assert response["Location"] == target

    @pytest.mark.parametrize("hostile", ["/rooms/", PREFIX + "/../rooms/", PREFIX + "x/"])
    def test_a_next_outside_the_prefix_is_not_followed(
        self, client: Client, alice: User, prefixed: str, hostile: str
    ) -> None:
        response = client.post(
            reverse("account_login"), {"login": alice.email, "password": PASSWORD, "next": hostile}
        )
        assert response["Location"] == reverse("index")

    def test_a_signed_out_visit_asks_to_sign_in_under_the_prefix(
        self, client: Client, alice_home: Home, prefixed: str
    ) -> None:
        today = reverse("tasks:today", kwargs={"home_id": alice_home.id})
        assert today.startswith(PREFIX + "/")
        response = client.get(today)
        assert response.status_code == 302
        assert response["Location"] == f"{reverse('account_login')}?next={quote(today, safe='/')}"


class TestToday:
    def test_today_links_only_under_the_prefix(
        self, signed_in: Client, alice_home: Home, owner_task: Task
    ) -> None:
        response = signed_in.get(reverse("tasks:today", kwargs={"home_id": alice_home.id}))
        assert response.status_code == 200
        html = response.content.decode()
        assert PREFIX + "/static/" in html
        assert outside(html) == []

    def test_a_proxy_that_removes_the_prefix_gets_the_same_page(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        today = reverse("tasks:today", kwargs={"home_id": alice_home.id})
        stripped = signed_in.get(today[len(PREFIX) :])
        assert stripped.status_code == 200
        assert outside(stripped.content.decode()) == []

    @pytest.mark.parametrize("route", ["index", "more", "rooms", "api-tokens:list", "about"])
    def test_the_main_pages_link_only_under_the_prefix(
        self, signed_in: Client, alice_home: Home, route: str
    ) -> None:
        response = signed_in.get(reverse(route), follow=True)
        assert response.status_code == 200
        assert outside(response.content.decode()) == []

    def test_the_static_files_are_served_under_the_prefix(self, signed_in: Client) -> None:
        # Served by Django's static view in tests; WhiteNoise reads the same path.
        response = signed_in.get(reverse("manifest"))
        icon = json.loads(response.content)["icons"][0]["src"]
        assert icon.startswith(PREFIX + "/static/")


class TestCreateAndDelete:
    def test_a_task_created_from_an_item_goes_back_to_it(
        self, signed_in: Client, alice_home: Home, owner_item: Item
    ) -> None:
        item_url = reverse(
            "rooms:item-detail", kwargs={"home_id": alice_home.id, "item_id": owner_item.id}
        )
        create = reverse("tasks:create", kwargs={"home_id": alice_home.id})
        form = signed_in.get(f"{create}?item={owner_item.id}&next={quote(item_url)}")
        assert f'<input type="hidden" name="next" value="{item_url}">' in form.content.decode()
        assert outside(form.content.decode()) == []
        response = signed_in.post(create, {**TASK_FORM, "item": owner_item.id, "next": item_url})
        assert response.status_code == 302
        assert response["Location"] == item_url
        page = signed_in.get(item_url).content.decode()
        assert "Task added" in page
        assert outside(page) == []

    def test_a_room_deleted_from_its_list_goes_back_to_the_list(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        listing = reverse("rooms:list", kwargs={"home_id": alice_home.id})
        assert listing.startswith(PREFIX + "/")
        response = signed_in.post(
            reverse("rooms:delete", kwargs={"home_id": alice_home.id, "room_id": owner_room.id}),
            {"next": listing},
        )
        assert response.status_code == 302
        assert response["Location"] == listing

    def test_the_back_link_is_named_from_a_prefixed_next(
        self, signed_in: Client, alice_home: Home, owner_task: Task
    ) -> None:
        today = reverse("tasks:today", kwargs={"home_id": alice_home.id})
        assert today.startswith(PREFIX + "/")
        detail = reverse(
            "tasks:detail", kwargs={"home_id": alice_home.id, "task_id": owner_task.id}
        )
        html = signed_in.get(f"{detail}?next={quote(today)}").content.decode()
        found = re.findall(r'<a class="back-link" href="([^"]*)"[^>]*>(.*?)</a>', html, re.S)
        links = [(href, re.sub(r"<[^>]+>", "", text).strip()) for href, text in found]
        assert links == [(today, "Today")]


class TestReturnRule:
    @pytest.mark.parametrize(
        "hostile",
        [
            # Refused at the root too: "//evil.example.com/", "https://evil.example.com/...".
            "/rooms/",
            PREFIX + "x/",
            PREFIX + "/../rooms/",
            PREFIX + "/%2e%2e/rooms/",
            PREFIX + "/.%2E/%2e%2e/rooms/",
            PREFIX + "/..\\rooms/",
        ],
    )
    def test_a_next_outside_the_prefix_is_refused(self, prefixed: str, hostile: str) -> None:
        request = RequestFactory().get("/", {"next": hostile})
        assert navigation.safe_next(request) is None

    def test_a_next_under_the_prefix_is_kept(self, prefixed: str) -> None:
        request = RequestFactory().get("/", {"next": PREFIX + "/rooms/"})
        assert navigation.safe_next(request) == PREFIX + "/rooms/"
        assert in_application(PREFIX)

    def test_at_the_root_every_path_is_in_the_application(self) -> None:
        assert in_application("/rooms/../x")


class TestManifest:
    def test_the_installed_application_opens_and_stays_under_the_prefix(
        self, signed_in: Client
    ) -> None:
        data = json.loads(signed_in.get(reverse("manifest")).content)
        assert data["start_url"] == PREFIX + "/"
        assert data["scope"] == PREFIX + "/"
        assert all(icon["src"].startswith(PREFIX + "/static/") for icon in data["icons"])

    def test_the_security_policy_is_the_same_under_the_prefix(self, signed_in: Client) -> None:
        response = signed_in.get(reverse("manifest"))
        assert json.loads(response.content)["scope"] == PREFIX + "/"
        policy = response["Content-Security-Policy"]
        assert PREFIX not in policy
        assert "default-src 'none'" in policy


class TestApi:
    def test_the_api_answers_under_the_prefix(self, signed_in: Client, alice_home: Home) -> None:
        homes = signed_in.get(PREFIX + "/api/v1/homes/")
        assert homes.status_code == 200
        assert str(alice_home.id) in homes.content.decode()

    def test_the_undated_tasks_filter_answers_under_the_prefix(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        services.create_task(alice, alice_home, title="Undated")
        services.create_task(alice, alice_home, title="Dated", due_on=datetime.date(2030, 1, 1))
        found = signed_in.get(f"{PREFIX}/api/v1/homes/{alice_home.id}/tasks/?due=none")
        assert found.status_code == 200
        assert [t["title"] for t in json.loads(found.content)["results"]] == ["Undated"]
        refused = signed_in.get(f"{PREFIX}/api/v1/homes/{alice_home.id}/tasks/?due=soon")
        assert refused.status_code == 400

    def test_the_tokens_screen_and_api_answer_under_the_prefix(self, signed_in: Client) -> None:
        screen = signed_in.get(reverse("api-tokens:list"))
        assert screen.status_code == 200
        assert outside(screen.content.decode()) == []
        assert signed_in.get(PREFIX + "/api/v1/me/tokens/").status_code == 200

    def test_the_schema_says_where_the_api_is(self, signed_in: Client) -> None:
        schema = json.loads(signed_in.get(reverse("api-schema") + "?format=json").content)
        assert schema["servers"] == [{"url": PREFIX}]
        assert any(path.startswith("/api/v1/") for path in schema["paths"])


class TestLinksSentAway:
    def test_an_invitation_link_carries_the_prefix(self, prefixed: str) -> None:
        link = home_emails.invitation_link("https://home.example.com", "secret")
        assert link == f"https://home.example.com{PREFIX}/invitations/secret/"

    def test_a_qr_label_carries_the_prefix(self, prefixed: str) -> None:
        label: Any = SimpleNamespace(code="ABCD")
        address = label_services.address("https://home.example.com/", label)
        assert address == f"https://home.example.com{PREFIX}/l/ABCD/"

    def test_the_calendar_feed_links_carry_the_prefix(
        self, alice: User, alice_home: Home, owner_task: Task, prefixed: str
    ) -> None:
        feed, _raw = feeds.create_feed(alice, alice_home)
        body = ics.render(feed, "https://home.example.com")
        urls = [str(event["URL"]) for event in Calendar.from_ical(body).walk("VEVENT")]
        assert urls
        assert all(url.startswith(f"https://home.example.com{PREFIX}/h/") for url in urls)

    def test_the_feed_address_shown_carries_the_prefix(self, signed_in: Client) -> None:
        response = signed_in.post(reverse("calendar:feeds"), {})
        html = signed_in.get(reverse("calendar:feeds")).content.decode()
        assert response.status_code in {200, 302}
        assert outside(html) == []


class TestHealth:
    def test_the_health_check_answers_over_http_under_the_prefix(
        self, client: Client, settings: SettingsWrapper, prefixed: str
    ) -> None:
        settings.SECURE_SSL_REDIRECT = True
        assert client.get(PREFIX + "/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200


# ---------- the prefix given by a trusted proxy ----------


class TestHeader:
    def test_a_trusted_proxy_sets_the_prefix(self, client: Client, header_mode: None) -> None:
        response = client.get("/manifest.webmanifest", HTTP_X_INGRESS_PATH=PREFIX)
        assert json.loads(response.content)["scope"] == PREFIX + "/"
        page = client.get("/accounts/login/", HTTP_X_INGRESS_PATH=PREFIX)
        assert outside(page.content.decode()) == []
        assert page.cookies["csrftoken"]["path"] == PREFIX

    @pytest.mark.parametrize(
        ("named", "peer", "value"),
        [
            (False, "127.0.0.1", PREFIX),
            (True, "192.0.2.50", PREFIX),
            (True, "127.0.0.1", "/a/../b"),
            (True, "127.0.0.1", "//evil.example.com"),
            (True, "127.0.0.1", "https://evil.example.com/"),
        ],
    )
    def test_the_header_counts_only_when_named_from_a_trusted_proxy_and_a_path(
        self, client: Client, settings: SettingsWrapper, named: bool, peer: str, value: str
    ) -> None:
        settings.HOUSECAIRN_URL_PREFIX_HEADER = "X-Ingress-Path"
        trusted = client.get("/manifest.webmanifest", HTTP_X_INGRESS_PATH=PREFIX)
        set_script_prefix("/")
        assert json.loads(trusted.content)["scope"] == PREFIX + "/"
        if not named:
            settings.HOUSECAIRN_URL_PREFIX_HEADER = ""
        response = client.get("/manifest.webmanifest", HTTP_X_INGRESS_PATH=value, REMOTE_ADDR=peer)
        set_script_prefix("/")
        assert json.loads(response.content)["scope"] == "/"


# ---------- no address written for the root ----------

# Attributes that hold an address, with a value that starts at the root of the site.
_ROOT_ADDRESS = re.compile(
    r"""\b(?:href|src|action|formaction|poster|hx-(?:get|post|put|patch|delete)|data-[\w-]*url)"""
    r"""\s*=\s*["']/""",
    re.IGNORECASE,
)
# A string in a script that starts at the root of the site, such as fetch('/api/...').
_ROOT_STRING = re.compile(r"""["'`]/[A-Za-z]""")


def test_no_template_nor_script_writes_an_address_at_the_root() -> None:
    """Under a prefix, `/...` leaves the application: addresses come from {% url %}."""
    templates = [
        f"{path.relative_to(SRC)}:{number}"
        for path in sorted(SRC.rglob("templates/**/*.html"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _ROOT_ADDRESS.search(line)
    ]
    scripts = [
        f"{path.relative_to(SRC)}:{number}"
        for path in sorted((SRC / "static" / "js").glob("*.js"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _ROOT_STRING.search(line) and not line.lstrip().startswith("//")
    ]
    assert templates + scripts == []
