"""A mail server that fails never ends a request of allauth in a server error.

The error is injected where the trace of production has it: `smtplib.SMTP.sendmail`, under
the real `housecairn.instance.mail.EmailBackend` (not under the test backend).
"""

import smtplib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse

from housecairn.accounts.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "a-long-and-unusual-passphrase"
NEW_PASSWORD = "another-long-unusual-passphrase-1"
ADDRESS = "person@example.com"
REAL_BACKEND = {
    "EMAIL_BACKEND": "housecairn.instance.mail.EmailBackend",
    "EMAIL_HOST": "mail.example.com",
    "EMAIL_PORT": 2525,
    "EMAIL_USE_TLS": False,
    "EMAIL_HOST_USER": "",
    "EMAIL_HOST_PASSWORD": "",
    "ACCOUNT_EMAIL_NOTIFICATIONS": True,
}


def recipients_refused(address: str = ADDRESS) -> smtplib.SMTPRecipientsRefused:
    """The error of the trace: the server refuses the recipient at RCPT TO, quoting it."""
    return smtplib.SMTPRecipientsRefused({address: (550, b"5.1.1 user unknown")})


@contextmanager
def server_refusing(error: Exception) -> Iterator[mock.Mock]:
    """The real backend, talking to a server that accepts the connection and then fails."""
    smtp = mock.MagicMock()
    smtp.sendmail.side_effect = error
    with (
        override_settings(**REAL_BACKEND),
        mock.patch("smtplib.SMTP", return_value=smtp),
    ):
        yield smtp.sendmail


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client() -> Client:
    return Client(raise_request_exception=False)


def person(email: str = ADDRESS, *, verified: bool = True) -> User:
    user = User.objects.create_user(email=email, password=PASSWORD)
    EmailAddress.objects.create(user=user, email=email, primary=True, verified=verified)
    return user


def message_of(response: Any) -> str:
    return " ".join(str(m) for m in response.context["messages"])


class TestViewsAnswerThePerson:
    """The page comes back with the reason, whoever asked and whatever the address."""

    @pytest.mark.parametrize("known", [True, False], ids=["known", "unknown"])
    def test_password_reset_answers_the_same_for_a_known_and_an_unknown_address(
        self, client: Client, known: bool
    ) -> None:
        if known:
            person()
        with server_refusing(recipients_refused()) as sendmail:
            response = client.post(
                reverse("account_reset_password"), {"email": ADDRESS}, follow=True
            )
        assert sendmail.called
        assert response.status_code == 200
        assert response.redirect_chain == [(reverse("account_reset_password"), 302)]
        assert "could not be sent" in message_of(response)

    def test_sign_in_with_an_unverified_address_when_verification_is_mandatory(
        self, client: Client
    ) -> None:
        person(verified=False)
        with (
            override_settings(ACCOUNT_EMAIL_VERIFICATION="mandatory"),
            server_refusing(recipients_refused()) as sendmail,
        ):
            response = client.post(
                reverse("account_login"), {"login": ADDRESS, "password": PASSWORD}, follow=True
            )
        assert sendmail.called
        assert response.status_code == 200
        assert "could not be sent" in message_of(response)
        assert "_auth_user_id" not in client.session

    def test_adding_an_address_keeps_it_and_says_the_message_did_not_leave(
        self, client: Client
    ) -> None:
        user = person()
        client.force_login(user)
        with server_refusing(recipients_refused("other@example.com")) as sendmail:
            response = client.post(
                reverse("account_email"),
                {"action_add": "", "email": "other@example.com"},
                follow=True,
            )
        assert sendmail.called
        assert response.status_code == 200
        assert "could not be sent" in message_of(response)

    def test_the_verification_can_be_asked_again_once_the_server_answers(
        self, client: Client
    ) -> None:
        user = person()
        EmailAddress.objects.create(user=user, email="other@example.com", verified=False)
        client.force_login(user)
        post = {"action_send": "", "email": "other@example.com"}
        with server_refusing(recipients_refused("other@example.com")) as sendmail:
            response = client.post(reverse("account_email"), post, follow=True)
        assert sendmail.called
        assert response.status_code == 200
        assert "could not be sent" in message_of(response)
        # The failed try did not use up the cooldown of the address.
        with override_settings(EMAIL_HOST="mail.example.com"):
            client.post(reverse("account_email"), post)
        assert [m.to for m in mail.outbox] == [["other@example.com"]]

    def test_the_address_is_not_in_the_log(
        self, client: Client, caplog: pytest.LogCaptureFixture
    ) -> None:
        person()
        with (
            caplog.at_level("DEBUG"),
            server_refusing(recipients_refused()) as sendmail,
        ):
            client.post(reverse("account_reset_password"), {"email": ADDRESS})
        assert sendmail.called
        assert "SMTPRecipientsRefused" in caplog.text
        assert ADDRESS not in caplog.text


class TestSecurityNoticesAreBestEffort:
    """What the person did succeeds; the notice that fails is in the log, not in a 500."""

    def test_changing_the_password(self, client: Client, caplog: pytest.LogCaptureFixture) -> None:
        user = person()
        client.force_login(user)
        with (
            caplog.at_level("WARNING", logger="housecairn.mail"),
            server_refusing(recipients_refused()) as sendmail,
        ):
            response = client.post(
                reverse("account_change_password"),
                {
                    "oldpassword": PASSWORD,
                    "password1": NEW_PASSWORD,
                    "password2": NEW_PASSWORD,
                },
            )
        assert sendmail.called
        assert response.status_code == 302
        user.refresh_from_db()
        assert user.check_password(NEW_PASSWORD)
        assert "Security notice not sent" in caplog.text

    def test_changing_the_primary_address(
        self, client: Client, caplog: pytest.LogCaptureFixture
    ) -> None:
        user = person()
        second = EmailAddress.objects.create(user=user, email="second@example.com", verified=True)
        client.force_login(user)
        with (
            caplog.at_level("WARNING", logger="housecairn.mail"),
            server_refusing(recipients_refused()) as sendmail,
        ):
            response = client.post(
                reverse("account_email"), {"action_primary": "", "email": second.email}
            )
        assert sendmail.called
        assert response.status_code == 302
        second.refresh_from_db()
        assert second.primary
        assert "Security notice not sent" in caplog.text


class TestOnlyTheSendIsTheMailServer:
    def test_a_template_that_cannot_be_read_is_a_defect_not_a_mail_failure(self) -> None:
        person()
        with (
            server_refusing(recipients_refused()),
            mock.patch(
                "housecairn.accounts.adapters.AccountAdapter.render_mail",
                side_effect=OSError("template unreadable"),
            ),
            pytest.raises(OSError, match="template unreadable"),
        ):
            Client().post(reverse("account_reset_password"), {"email": ADDRESS})
