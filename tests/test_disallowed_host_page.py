"""The 400 page of a host name the instance refuses (core/views.py, core/hosthint.py).

A host that serves the application for someone else sets the sentence the page shows; the
page never repeats the refused name and never lists `ALLOWED_HOSTS`.
"""

import os
import runpy
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured, SuspiciousOperation
from django.test import Client, RequestFactory
from pytest_django.fixtures import Settings as SettingsWrapper

from housecairn.core import views
from housecairn.core.hosthint import MAX_LENGTH, parse_hint

SETTINGS_FILE = Path(__file__).resolve().parents[1] / "src" / "housecairn" / "settings.py"
GENERIC = "Its administrator must add the name to ALLOWED_HOSTS."
HOSTILE = "evil-name.attacker.example"
HINT = "Add this name to the allowed_hosts option of the add-on."


def refused(client: Client, host: str = HOSTILE) -> Any:
    return client.get("/", HTTP_HOST=host)


def computed_settings(**variables: str) -> dict[str, Any]:
    with mock.patch.dict(os.environ, variables):
        return runpy.run_path(str(SETTINGS_FILE))


@pytest.mark.django_db
class TestPage:
    def test_without_a_hint_the_page_gives_the_generic_sentence(self, client: Client) -> None:
        answer = refused(client)
        assert answer.status_code == 400
        assert GENERIC in answer.content.decode()

    def test_with_a_hint_the_page_shows_it_instead(
        self, client: Client, settings: SettingsWrapper
    ) -> None:
        settings.HOUSECAIRN_DISALLOWED_HOST_HINT = HINT
        answer = refused(client)
        assert answer.status_code == 400
        page = answer.content.decode()
        assert HINT in page
        assert GENERIC not in page

    def test_the_hint_is_escaped(self, client: Client, settings: SettingsWrapper) -> None:
        settings.HOUSECAIRN_DISALLOWED_HOST_HINT = "<script>alert(1)</script> & more"
        page = refused(client).content.decode()
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more" in page

    def test_the_refused_name_is_not_repeated(
        self, client: Client, settings: SettingsWrapper
    ) -> None:
        settings.HOUSECAIRN_DISALLOWED_HOST_HINT = HINT
        for host in (HOSTILE, "evil<script>.example", "bad host:99999"):
            page = refused(client, host).content.decode()
            assert host not in page
            assert "evil" not in page
            assert "attacker" not in page

    def test_the_allowed_hosts_are_not_listed(
        self, client: Client, settings: SettingsWrapper
    ) -> None:
        settings.ALLOWED_HOSTS = ["testserver", "secret-internal.example"]
        page = refused(client).content.decode()
        assert "secret-internal.example" not in page

    def test_another_400_keeps_the_page_without_the_sentence(self) -> None:
        request = RequestFactory().get("/")
        answer = views.bad_request(request, SuspiciousOperation("other"))
        assert answer.status_code == 400
        page = answer.content.decode()
        assert "The request could not be understood." in page
        assert GENERIC not in page

    def test_another_400_does_not_show_the_hint(self, settings: SettingsWrapper) -> None:
        settings.HOUSECAIRN_DISALLOWED_HOST_HINT = HINT
        answer = views.bad_request(RequestFactory().get("/"), SuspiciousOperation("other"))
        assert HINT not in answer.content.decode()

    def test_the_french_page_has_the_sentence_in_french(self, client: Client) -> None:
        answer = client.get("/", HTTP_HOST=HOSTILE, headers={"accept-language": "fr"})
        page = answer.content.decode()
        assert answer.status_code == 400
        assert "Son administrateur doit ajouter ce nom à ALLOWED_HOSTS." in page
        assert GENERIC not in page


class TestSetting:
    def test_the_default_is_empty(self) -> None:
        assert computed_settings()["HOUSECAIRN_DISALLOWED_HOST_HINT"] == ""

    def test_the_variable_is_read(self) -> None:
        found = computed_settings(HOUSECAIRN_DISALLOWED_HOST_HINT=f"  {HINT} ")
        assert found["HOUSECAIRN_DISALLOWED_HOST_HINT"] == HINT

    def test_a_text_too_long_is_refused_at_start_up(self) -> None:
        with pytest.raises(ImproperlyConfigured):
            computed_settings(HOUSECAIRN_DISALLOWED_HOST_HINT="x" * (MAX_LENGTH + 1))

    def test_the_longest_text_is_accepted(self) -> None:
        assert parse_hint("x" * MAX_LENGTH) == "x" * MAX_LENGTH

    def test_a_null_character_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured):
            parse_hint("a\x00b")

    @pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\tb", "a\x1bb", "a\x7fb"])
    def test_a_control_character_is_refused_at_start_up(self, bad: str) -> None:
        with pytest.raises(ImproperlyConfigured):
            computed_settings(HOUSECAIRN_DISALLOWED_HOST_HINT=bad)
