"""Account screens: no dead link without mail, landing page, names in messages, headings."""

import re

import pytest
from django.contrib.messages import get_messages
from django.test import Client, override_settings
from django.urls import reverse

from housecairn.accounts.models import User
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db

NO_MAIL = {"EMAIL_HOST": "", "ACCOUNT_EMAIL_NOTIFICATIONS": False}
MAIL = {
    "EMAIL_HOST": "smtp.example.com",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "ACCOUNT_EMAIL_NOTIFICATIONS": True,
}


class TestForgottenPasswordLink:
    @override_settings(**NO_MAIL)
    def test_the_password_change_page_has_no_dead_link_without_mail(
        self, client: Client, alice: User
    ) -> None:
        client.force_login(alice)
        response = client.get(reverse("account_change_password"))
        assert response.status_code == 200
        assert reverse("account_reset_password") not in response.text
        assert "Forgot" not in response.text

    @override_settings(**MAIL)
    def test_the_link_stays_when_mail_works(self, client: Client, alice: User) -> None:
        client.force_login(alice)
        response = client.get(reverse("account_change_password"))
        assert reverse("account_reset_password") in response.text


class TestLandingPage:
    def test_sign_in_lands_on_my_home(self, client: Client, alice: User) -> None:
        response = client.post(
            reverse("account_login"), {"login": alice.email, "password": PASSWORD}
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("my-home")

    def test_an_explicit_next_wins(self, client: Client, alice: User) -> None:
        target = reverse("homes:list")
        response = client.post(
            reverse("account_login") + f"?next={target}",
            {"login": alice.email, "password": PASSWORD},
        )
        assert response["Location"] == target


class TestMessagesNameThePerson:
    def test_signing_in_greets_by_display_name_not_address(self, client: Client) -> None:
        person = User.objects.create_user(
            email="hidden.address@example.com", password=PASSWORD, display_name="Camille"
        )
        response = client.post(
            reverse("account_login"), {"login": person.email, "password": PASSWORD}
        )
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("Camille" in t for t in texts)
        assert not any("hidden.address" in t or "@" in t for t in texts)

    def test_without_a_display_name_the_message_still_has_no_address(self, client: Client) -> None:
        person = User.objects.create_user(email="lea.bernard@example.com", password=PASSWORD)
        response = client.post(
            reverse("account_login"), {"login": person.email, "password": PASSWORD}
        )
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("lea.bernard" in t for t in texts)
        assert not any("@" in t for t in texts)


class TestHeadingLevels:
    def headings(self, html: str) -> list[str]:
        return re.findall(r"<h([1-6])\b", html)

    def test_about_has_no_skipped_level(self, client: Client) -> None:
        levels = self.headings(client.get(reverse("about")).text)
        assert "3" not in levels
        assert levels[:2] == ["1", "2"]

    def test_the_panel_template_uses_h2(self) -> None:
        from django.template.loader import get_template

        source = get_template("allauth/elements/panel.html").template.source
        assert "<h3" not in source
        assert "<h2" in source
