"""Behind Home Assistant's Ingress: framing by the same origin, links sent away (docs/adr/0055).

Two decisions of 2026-11-10. `HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING` (off by default) lets a
page of the same origin show HouseCairn in a frame, and nothing else changes in the security
headers. A link made to leave the application (calendar feed, QR label, invitation, email) is
always on `HOUSECAIRN_SITE_URL` plus the fixed `HOUSECAIRN_URL_PREFIX`, never on the prefix a
proxy gives in a header, which only works through that proxy.
"""

import os
import re
import runpy
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from django.urls import reverse, set_script_prefix
from icalendar import Calendar
from pytest_django.fixtures import Settings as SettingsWrapper

from housecairn.accounts.models import User
from housecairn.calendar import feeds
from housecairn.core.links import external_url
from housecairn.homes.models import Home
from housecairn.rooms.models import Room
from housecairn.tasks.models import Task

pytest_plugins = ("tests.rooms_fixtures", "tests.tasks_fixtures")

pytestmark = pytest.mark.django_db

SRC = Path(__file__).resolve().parents[1] / "src" / "housecairn"
VARIABLE = "HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING"
# The path Ingress gives in its header, and the public address of the instance.
INGRESS = "/api/hassio_ingress/0123abcdEF-_x"
SITE = "https://home.example.com"
FIXED = "/housecairn"
PUBLIC = SITE + FIXED
EMAIL = {
    "EMAIL_HOST": "smtp.example.com",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
}


def computed_settings(**variables: str) -> dict[str, Any]:
    """The module-level names of settings.py, run with these environment variables."""
    environ = {k: v for k, v in os.environ.items() if k != VARIABLE}
    environ.update(variables)
    with mock.patch.dict(os.environ, environ, clear=True):
        return runpy.run_path(str(SRC / "settings.py"))


def directives(response: Any) -> dict[str, str]:
    policy = response["Content-Security-Policy"]
    return dict(d.strip().split(" ", 1) for d in policy.split(";") if d.strip())


def headers_with(settings: SettingsWrapper, client: Client, **variables: str) -> Any:
    found = computed_settings(**variables)
    settings.X_FRAME_OPTIONS = found["X_FRAME_OPTIONS"]
    settings.CONTENT_SECURITY_POLICY = found["CONTENT_SECURITY_POLICY"]
    return client.get(reverse("account_login"))


# ---------- framing ----------


class TestFraming:
    def test_off_by_default_nothing_changes(
        self, settings: SettingsWrapper, client: Client
    ) -> None:
        found = computed_settings()
        assert found[VARIABLE] is False
        response = headers_with(settings, client)
        assert response["X-Frame-Options"] == "DENY"
        assert directives(response)["frame-ancestors"] == "'none'"

    def test_on_a_page_of_the_same_origin_may_frame_it(
        self, settings: SettingsWrapper, client: Client
    ) -> None:
        response = headers_with(settings, client, **{VARIABLE: "true"})
        assert response["X-Frame-Options"] == "SAMEORIGIN"
        assert directives(response)["frame-ancestors"] == "'self'"

    def test_the_rest_of_the_policy_is_the_same(
        self, settings: SettingsWrapper, client: Client
    ) -> None:
        off = directives(headers_with(settings, client, **{VARIABLE: "false"}))
        on = directives(headers_with(settings, client, **{VARIABLE: "true"}))
        assert off.pop("frame-ancestors") != on.pop("frame-ancestors")
        assert off == on
        assert off["default-src"] == "'none'"

    @pytest.mark.parametrize("value", ["maybe", "sameorigin", "2"])
    def test_a_value_that_is_not_true_or_false_stops_the_start(self, value: str) -> None:
        with pytest.raises(ImproperlyConfigured, match=VARIABLE):
            computed_settings(**{VARIABLE: value})


# ---------- links sent away, with the prefix given by Ingress ----------


@pytest.fixture
def ingress(settings: SettingsWrapper) -> Iterator[None]:
    """A fixed prefix and a public address; Ingress gives its own path in X-Ingress-Path."""
    settings.HOUSECAIRN_URL_PREFIX_HEADER = "X-Ingress-Path"
    settings.HOUSECAIRN_URL_PREFIX = FIXED
    settings.HOUSECAIRN_SITE_URL = SITE
    # The proxy removes its path: the tests ask for the routes at the root, whatever the
    # prefix the suite runs under (the CI step "Tests under a path prefix").
    set_script_prefix("/")
    cache.clear()
    yield
    cache.clear()
    set_script_prefix("/")


@pytest.fixture
def through_ingress(client: Client, alice: User, ingress: None) -> Client:
    """Alice's browser in the Ingress panel: every request comes through the trusted proxy."""
    client.force_login(alice)
    client.defaults["HTTP_X_INGRESS_PATH"] = INGRESS
    return client


def urls_in(text: str) -> list[str]:
    return re.findall(r"https?://[^\s\"<>]+", text)


class TestLinksSentAwayThroughIngress:
    def test_the_links_of_a_calendar_feed_are_public(
        self, through_ingress: Client, alice: User, alice_home: Home, owner_task: Task
    ) -> None:
        _feed, raw = feeds.create_feed(alice, alice_home)
        body = through_ingress.get(reverse("calendar:feed", kwargs={"token": raw})).content
        urls = [str(e["URL"]) for e in Calendar.from_ical(body).walk("VEVENT")]
        assert urls
        assert all(url.startswith(PUBLIC + "/h/") for url in urls), urls

    def test_the_address_of_a_new_feed_is_public(
        self, through_ingress: Client, alice_home: Home
    ) -> None:
        created = through_ingress.post(
            reverse("api-v1:calendar-feed-list"),
            {"home": str(alice_home.id)},
            content_type="application/json",
        )
        assert created.status_code == 201
        assert created.json()["url"].startswith(PUBLIC + "/calendar/feed/")

    def test_the_address_of_a_qr_label_is_public(
        self, through_ingress: Client, alice_home: Home, owner_room: Room
    ) -> None:
        created = through_ingress.post(
            reverse("api-v1:home-label-list", kwargs={"home_id": alice_home.id}),
            {"kind": "room", "target": str(owner_room.id)},
            content_type="application/json",
        )
        assert created.status_code == 201
        data = created.json()
        assert data["url"] == f"{PUBLIC}/l/{data['code']}/"

    def test_an_invitation_email_links_to_the_public_address(
        self, through_ingress: Client, settings: SettingsWrapper, alice_home: Home
    ) -> None:
        for name, value in EMAIL.items():
            setattr(settings, name, value)
        through_ingress.post(
            reverse("homes:invite", kwargs={"home_id": alice_home.id}),
            {"email": "new@example.com", "role": "member"},
        )
        [message] = mail.outbox
        [link] = [u for u in urls_in(message.body) if "/invitations/" in u]
        assert link.startswith(PUBLIC + "/invitations/hci_")

    def test_a_reset_email_links_to_the_public_address(
        self, client: Client, settings: SettingsWrapper, alice: User, ingress: None
    ) -> None:
        for name, value in EMAIL.items():
            setattr(settings, name, value)
        client.post(
            reverse("account_reset_password"), {"email": alice.email}, HTTP_X_INGRESS_PATH=INGRESS
        )
        [message] = mail.outbox
        urls = [u for u in urls_in(message.body) if "/password/reset/key/" in u]
        assert urls
        assert all(u.startswith(PUBLIC + "/accounts/password/reset/key/") for u in urls), urls
        assert INGRESS not in message.body


class TestExternalUrl:
    def test_the_prefix_of_the_request_is_replaced_by_the_fixed_one(
        self, settings: SettingsWrapper
    ) -> None:
        settings.HOUSECAIRN_URL_PREFIX = FIXED
        set_script_prefix(INGRESS + "/")
        try:
            assert external_url(INGRESS + "/l/ABCD/?a=1#b", SITE + "/") == PUBLIC + "/l/ABCD/?a=1#b"
            assert external_url(INGRESS, SITE) == PUBLIC + "/"
        finally:
            set_script_prefix("/")

    def test_at_the_root_and_without_a_site(self, settings: SettingsWrapper) -> None:
        settings.HOUSECAIRN_URL_PREFIX = ""
        assert external_url("/l/ABCD/", SITE) == SITE + "/l/ABCD/"
        assert external_url("/l/ABCD/", "") == ""
