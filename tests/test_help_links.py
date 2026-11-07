"""Help link of each screen, to its page of the documentation site (docs/adr/0016)."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.test import Client, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from housecairn.accounts.models import User
from housecairn.core import help as help_links
from housecairn.homes.models import Home

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
# Set by the Documentation job of CI to the built site (scripts/build_docs.py).
BUILT_SITE = os.environ.get("HOUSECAIRN_DOCS_SITE")


def route_names(patterns: list[URLPattern | URLResolver], namespace: str = "") -> Iterator[str]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            inner = namespace + (f"{pattern.namespace}:" if pattern.namespace else "")
            yield from route_names(pattern.url_patterns, inner)
        elif pattern.name:
            yield namespace + pattern.name


def all_routes() -> list[str]:
    return sorted(set(route_names(get_resolver().url_patterns)))


def pages() -> list[str]:
    return sorted({*help_links.HELP_PAGES.values(), *help_links.HELP_PREFIXES.values()})


def test_every_route_is_a_screen_with_help_or_declared_otherwise() -> None:
    routes = all_routes()
    assert "index" in routes
    unclassified = [
        route
        for route in routes
        if help_links.help_page(route) is None and not route.startswith(help_links.NOT_SCREENS)
    ]
    assert unclassified == []


def test_screens_with_help_are_routes() -> None:
    assert set(help_links.HELP_PAGES) <= set(all_routes())


@pytest.mark.parametrize("page", pages())
def test_help_page_has_a_source_page(page: str) -> None:
    name = page.rstrip("/")
    assert (DOCS_DIR / f"{name}.md").exists() or (DOCS_DIR / name / "index.md").exists()


@pytest.mark.skipif(not BUILT_SITE, reason="HOUSECAIRN_DOCS_SITE is not set")
@pytest.mark.parametrize("page", pages())
@pytest.mark.parametrize("prefix", sorted(help_links.DOCS_LANGUAGES.values()))
def test_help_page_exists_in_the_built_site(prefix: str, page: str) -> None:
    assert BUILT_SITE
    assert (Path(BUILT_SITE) / prefix / page / "index.html").is_file()


def test_help_url_follows_the_language() -> None:
    assert help_links.help_url("homes:list", "en") == "https://docs.housecairn.app/screens/homes/"
    assert help_links.help_url("homes:list", "fr") == (
        "https://docs.housecairn.app/fr/screens/homes/"
    )
    assert help_links.help_url("homes:list", "fr-ca") == (
        "https://docs.housecairn.app/fr/screens/homes/"
    )
    # A language the documentation does not have: English.
    assert help_links.help_url("index", "de") == "https://docs.housecairn.app/screens/start-page/"
    assert help_links.help_url("index", None) == "https://docs.housecairn.app/screens/start-page/"
    assert help_links.help_url("mfa_index", "en") == "https://docs.housecairn.app/screens/account/"
    assert help_links.help_url("healthz", "en") is None


@override_settings(HOUSECAIRN_DOCS_URL="https://help.example.com/housecairn")
def test_help_url_uses_the_configured_address() -> None:
    assert help_links.help_url("index", "fr") == (
        "https://help.example.com/housecairn/fr/screens/start-page/"
    )


@pytest.mark.django_db
class TestPages:
    def test_sign_in_page_links_to_its_help(self, client: Client) -> None:
        response = client.get(reverse("account_login"))
        assert 'href="https://docs.housecairn.app/screens/sign-in/"' in response.text
        assert 'rel="help"' in response.text

    def test_start_page_links_to_its_help_in_french(self, client: Client) -> None:
        response = client.get(reverse("index"), HTTP_ACCEPT_LANGUAGE="fr")
        assert 'href="https://docs.housecairn.app/fr/screens/start-page/"' in response.text
        assert 'aria-label="Aide sur cette page"' in response.text

    def test_home_pages_link_to_their_help(
        self, client: Client, alice: User, alice_home: Home
    ) -> None:
        client.force_login(alice)
        homes = client.get(reverse("homes:list"))
        home = client.get(reverse("homes:detail", kwargs={"home_id": alice_home.id}))
        assert 'href="https://docs.housecairn.app/screens/homes/"' in homes.text
        assert 'href="https://docs.housecairn.app/screens/home/"' in home.text

    def test_account_pages_link_to_their_help(self, client: Client, alice: User) -> None:
        client.force_login(alice)
        response = client.get(reverse("account_email"))
        assert 'href="https://docs.housecairn.app/screens/account/"' in response.text
