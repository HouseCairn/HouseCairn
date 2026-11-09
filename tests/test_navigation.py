"""The shell of the application (docs/adr/0017): its five sections, their tabs, the entry
marked as current, the roots without a back link, and More in four groups."""

import re
from collections.abc import Callable

import pytest
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home

pytest_plugins = ("tests.rooms_fixtures",)

pytestmark = pytest.mark.django_db


def more_groups(html: str) -> list[str]:
    """The headings of the groups of the More page, in order."""
    main = html.split('<main id="main"', 1)[1]
    return re.findall(r'<h2 id="more-[a-z]+">([^<]*)</h2>', main)


def main_part(html: str) -> str:
    return html.split('<main id="main"', 1)[1]


class TestMore:
    def test_a_person_sees_home_me_and_help(self, signed_in: Client, alice_home: Home) -> None:
        html = signed_in.get(reverse("more")).content.decode()
        assert more_groups(html) == ["Home", "Me", "Help"]

    def test_an_administrator_also_sees_the_instance(
        self, client: Client, site_admin: User
    ) -> None:
        client.force_login(site_admin)
        html = client.get(reverse("more")).content.decode()
        assert more_groups(html) == ["Home", "Me", "Instance", "Help"]
        assert reverse("instance:overview") in main_part(html)

    def test_the_instance_is_for_administrators_only(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        client.force_login(make_user("staff@example.com", is_staff=True))
        html = client.get(reverse("more")).content.decode()
        assert "Instance" not in more_groups(html)
        assert reverse("instance:overview") not in html

    def test_the_home_group_is_about_the_only_home(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        main = main_part(signed_in.get(reverse("more")).content.decode())
        kwargs = {"home_id": alice_home.id}
        for name in (
            "homes:detail",
            "homes:household",
            "reports:list",
            "tasks:contractors",
            "labels:list",
        ):
            assert reverse(name, kwargs=kwargs) in main, name
        assert reverse("homes:list") in main

    def test_with_two_homes_the_home_group_lists_them(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        home_services.create_home(alice, name="Cottage")
        main = main_part(signed_in.get(reverse("more")).content.decode())
        assert reverse("homes:list") in main
        assert reverse("homes:household", kwargs={"home_id": alice_home.id}) not in main

    def test_me_and_help(self, signed_in: Client) -> None:
        main = main_part(signed_in.get(reverse("more")).content.decode())
        for name in (
            "profile",
            "notifications:index",
            "display-preferences",
            "calendar:feeds",
            "more-security",
            "api-docs",
            "about",
            "account_logout",
        ):
            assert reverse(name) in main, name

    def test_deleting_the_account_is_not_on_more(self, signed_in: Client) -> None:
        main = main_part(signed_in.get(reverse("more")).content.decode())
        assert reverse("account_delete") not in main

    def test_security_ends_with_deleting_the_account(self, signed_in: Client) -> None:
        main = main_part(signed_in.get(reverse("more-security")).content.decode())
        assert reverse("mfa_index") in main
        assert reverse("account_change_password") in main
        assert main.index(reverse("account_delete")) > main.index(
            reverse("account_change_password")
        )
        assert "button-danger" in main

    def test_in_french(self, signed_in: Client, alice_home: Home) -> None:
        html = signed_in.get(reverse("more"), headers={"Accept-Language": "fr"}).content.decode()
        assert more_groups(html) == ["Logement", "Moi", "Aide"]
        security = signed_in.get(
            reverse("more-security"), headers={"Accept-Language": "fr"}
        ).content.decode()
        assert "Sécurité et connexion" in security
