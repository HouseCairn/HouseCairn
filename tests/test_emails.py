"""Transactional email: branded, in English and French, text and HTML (docs/adr/0023)."""

import re
from collections.abc import Callable, Iterator
from typing import Any
from unittest import mock

import pytest
from allauth.account.adapter import get_adapter
from allauth.account.models import EmailAddress
from allauth.core.context import request_context
from django.core import mail
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from housecairn.accounts import services
from housecairn.accounts.models import KnownDevice, User
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db

EMAIL = {
    "EMAIL_HOST": "smtp.example.com",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "ACCOUNT_EMAIL_NOTIFICATIONS": True,
}


@pytest.fixture(autouse=True)
def _email() -> Iterator[None]:
    cache.clear()
    with override_settings(**EMAIL):
        yield
    cache.clear()


def html_of(message: Any) -> str:
    html, mimetype = message.alternatives[0]
    assert mimetype == "text/html"
    return str(html)


def links(text: str) -> list[str]:
    return re.findall(r"https?://[^\s\"<>]+", text)


class TestPasswordReset:
    def test_reset_mail_is_branded_with_text_and_html(self, client: Client, alice: User) -> None:
        client.post(reverse("account_reset_password"), {"email": alice.email})
        [message] = mail.outbox
        assert message.to == [alice.email]
        assert message.subject.startswith("HouseCairn: ")
        assert "Hello from HouseCairn!" in message.body
        assert "Thank you for using HouseCairn." in message.body
        html = html_of(message)
        assert ">HouseCairn<" in html
        assert "<html" in html
        [url] = [u for u in links(message.body) if "/accounts/password/reset/key/" in u]
        assert f'href="{url}"' in html
        assert "testserver" not in message.body.replace("http://testserver/", "")

    def test_the_mail_in_french(self, client: Client, alice: User) -> None:
        client.post(
            reverse("account_reset_password"),
            {"email": alice.email},
            headers={"Accept-Language": "fr"},
        )
        [message] = mail.outbox
        assert "Bonjour de la part de HouseCairn" in message.body
        assert "Merci d'utiliser HouseCairn" in message.body
        assert 'lang="fr"' in html_of(message)

    @override_settings(HOUSECAIRN_SITE_URL="https://home.example.com")
    def test_links_use_the_public_address_not_the_host_header(
        self, client: Client, alice: User
    ) -> None:
        client.post(
            reverse("account_reset_password"),
            {"email": alice.email},
            headers={"Host": "testserver"},
        )
        [message] = mail.outbox
        urls = links(message.body)
        assert any(
            u.startswith("https://home.example.com/accounts/password/reset/key/") for u in urls
        )
        assert not any("testserver" in u for u in urls)
        assert all("testserver" not in u for u in links(html_of(message)))

    @override_settings(EMAIL_HOST="", ACCOUNT_EMAIL_NOTIFICATIONS=False)
    def test_without_mail_the_page_and_its_link_are_gone(self, client: Client) -> None:
        assert client.get(reverse("account_reset_password")).status_code == 404
        assert "Forgot" not in client.get(reverse("account_login")).text
        assert mail.outbox == []


class TestSecurityAlerts:
    def sign_in(self, client: Client, user: User) -> None:
        response = client.post(
            reverse("account_login"), {"login": user.email, "password": PASSWORD}
        )
        assert response.status_code == 302

    def test_changing_the_password_alerts_the_address(self, client: Client, alice: User) -> None:
        client.force_login(alice)
        mail.outbox.clear()
        response = client.post(
            reverse("account_change_password"),
            {
                "oldpassword": PASSWORD,
                "password1": "another-long-passphrase-1",
                "password2": "another-long-passphrase-1",
            },
        )
        assert response.status_code == 302
        [message] = mail.outbox
        assert message.to == [alice.email]
        assert "Password" in message.subject
        assert "Your password has been changed." in message.body
        assert "IP address" in message.body
        assert "Hello from HouseCairn!" in message.body
        assert "<html" in html_of(message)

    def test_a_passkey_or_authenticator_change_is_announced(self, alice: User) -> None:
        request = RequestFactory().get("/")
        request.user = alice
        with request_context(request):
            adapter = get_adapter(request)
            for prefix, text in (
                ("mfa/email/webauthn_added", "A new security key has been added."),
                ("mfa/email/webauthn_removed", "A security key has been removed."),
                ("mfa/email/totp_activated", "Authenticator app activated."),
                ("mfa/email/recovery_codes_generated", "recovery codes"),
            ):
                mail.outbox.clear()
                adapter.send_notification_mail(prefix, alice)
                [message] = mail.outbox
                assert text in message.body, prefix
                assert "Hello from HouseCairn!" in message.body
                assert message.subject.startswith("HouseCairn: ")
                assert "<html" in html_of(message)

    def test_the_first_sign_in_raises_no_alert_a_new_browser_does(
        self, client: Client, alice: User
    ) -> None:
        self.sign_in(client, alice)
        assert mail.outbox == []
        assert KnownDevice.objects.filter(user=alice).count() == 1
        cookie = client.cookies[services.DEVICE_COOKIE]
        assert cookie["httponly"]
        assert cookie["samesite"] == "Lax"
        # Same browser, signed in again (a real browser keeps its cookie): nothing.
        client.logout()
        client.cookies[services.DEVICE_COOKIE] = cookie.value
        self.sign_in(client, alice)
        assert mail.outbox == []
        assert KnownDevice.objects.filter(user=alice).count() == 1
        # Another browser: an alert, to the address of the account.
        other = Client(headers={"User-Agent": "Other Browser/1.0"})
        self.sign_in(other, alice)
        [message] = mail.outbox
        assert message.to == [alice.email]
        assert "New sign-in" in message.subject
        assert "Other Browser/1.0" in message.body
        assert "IP address" in message.body
        assert "<html" in html_of(message)
        assert KnownDevice.objects.filter(user=alice).count() == 2

    def test_only_a_digest_of_the_device_secret_is_kept(self, client: Client, alice: User) -> None:
        self.sign_in(client, alice)
        secret = client.cookies[services.DEVICE_COOKIE].value
        device = KnownDevice.objects.get()
        assert secret not in device.digest
        assert device.digest == services._digest(secret)

    def test_a_forged_cookie_is_no_known_device(self, client: Client, alice: User) -> None:
        self.sign_in(client, alice)
        mail.outbox.clear()
        thief = Client()
        thief.cookies[services.DEVICE_COOKIE] = "guessed-secret"
        self.sign_in(thief, alice)
        assert len(mail.outbox) == 1

    def test_another_account_cannot_use_the_cookie_of_a_known_device(
        self, client: Client, alice: User, bob: User
    ) -> None:
        self.sign_in(client, alice)
        alices_cookie = client.cookies[services.DEVICE_COOKIE].value
        client.logout()
        client.cookies[services.DEVICE_COOKIE] = alices_cookie
        self.sign_in(client, bob)  # bob's first device: no alert, alice's cookie is no help
        assert mail.outbox == []
        assert KnownDevice.objects.filter(user=bob).count() == 1
        other = Client()
        self.sign_in(other, bob)
        assert len(mail.outbox) == 1

    def test_a_mail_server_that_is_down_does_not_stop_the_sign_in(
        self, client: Client, alice: User
    ) -> None:
        self.sign_in(client, alice)
        other = Client()
        with mock.patch(
            "django.core.mail.message.EmailMultiAlternatives.send",
            side_effect=ConnectionRefusedError("smtp down"),
        ):
            self.sign_in(other, alice)
        assert other.session.get("_auth_user_id")

    @override_settings(EMAIL_HOST="", ACCOUNT_EMAIL_NOTIFICATIONS=False)
    def test_without_mail_nothing_is_recorded_or_sent(self, client: Client, alice: User) -> None:
        self.sign_in(client, alice)
        self.sign_in(Client(), alice)
        assert not KnownDevice.objects.exists()
        assert mail.outbox == []
        assert services.DEVICE_COOKIE not in client.cookies

    def test_old_devices_are_forgotten(self, client: Client, alice: User) -> None:
        for _i in range(services.MAX_KNOWN_DEVICES + 5):
            self.sign_in(Client(), alice)
        assert KnownDevice.objects.filter(user=alice).count() == services.MAX_KNOWN_DEVICES

    def test_an_account_without_an_address_record_is_still_alerted(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        user = make_user("carol@example.com")
        assert not EmailAddress.objects.filter(user=user).exists()
        self.sign_in(client, user)
        self.sign_in(Client(), user)
        assert [m.to for m in mail.outbox] == [["carol@example.com"]]


class TestVerificationMail:
    @override_settings(
        HOUSECAIRN_SIGNUP_OPEN=True,
        ACCOUNT_EMAIL_VERIFICATION="mandatory",
        HOUSECAIRN_SIGNUP_POW_BITS=8,
        HOUSECAIRN_SITE_URL="https://home.example.com",
    )
    def test_the_verification_link_is_on_the_public_address(self, client: Client) -> None:
        from housecairn.accounts import antibot

        page = client.get(reverse("account_signup")).text
        challenge = re.search(r'data-challenge="([0-9a-f]+)"', page)
        bits = re.search(r'data-bits="(\d+)"', page)
        assert challenge
        assert bits
        client.post(
            reverse("account_signup"),
            {
                "email": "new@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "pow_solution": antibot.solve(challenge.group(1), int(bits.group(1))),
            },
        )
        [message] = mail.outbox
        assert message.subject == "HouseCairn: Please Confirm Your Email Address"
        urls = [u for u in links(message.body) if "/accounts/confirm-email/" in u]
        assert urls
        assert all(u.startswith("https://home.example.com/") for u in urls)
        assert "<html" in html_of(message)


class TestLayout:
    def test_the_body_is_escaped_and_links_are_clickable(self) -> None:
        html = render_to_string(
            "account/email/layout.html",
            {
                "subject": "S <b>",
                "body": (
                    "Browser: <script>alert(1)</script>\nOpen https://example.com/x?a=1&b=2 now"
                ),
            },
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert '<a href="https://example.com/x?a=1&amp;b=2"' in html
        assert "<title>S &lt;b&gt;</title>" in html
