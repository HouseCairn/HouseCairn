"""A passkey challenge answered after a password sign-in (ADR 0018).

The sign-in page asks for a passkey challenge as soon as it loads (a GET of the passkey
login URL, which writes the challenge in the session). If the person submits their
password before that answer arrives, the two requests run side by side: the sign-in gives
the browser a new session, then the late challenge answers. The browser keeps the cookies
of the last answer, so the late answer must not hand it another session.

Before `accounts.views.LoginView`, the page had no session yet, the challenge created one,
and this test failed: the browser ended signed out right after signing in.
"""

from http.cookies import SimpleCookie
from typing import Any

import pytest
from allauth.mfa.webauthn import views as webauthn_views
from django.conf import settings
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def _signed_in(browser: Client) -> bool:
    return "_auth_user_id" in browser.session


def test_the_sign_in_page_opens_the_session(client: Client) -> None:
    response = client.get(reverse("account_login"))
    assert response.status_code == 200
    assert response.cookies[settings.SESSION_COOKIE_NAME].value
    # A second visit keeps it.
    assert settings.SESSION_COOKIE_NAME not in client.get(reverse("account_login")).cookies


def test_a_late_passkey_challenge_keeps_the_sign_in(alice: User, monkeypatch: Any) -> None:
    browser = Client()
    assert browser.get(reverse("account_login")).status_code == 200
    # The challenge leaves with the cookies the page gave; it answers after the sign-in.
    late = Client()
    late.cookies = SimpleCookie(browser.cookies.output(header="", sep=";"))
    begin = webauthn_views.auth.begin_authentication

    def answered_after_the_sign_in(*args: Any, **kwargs: Any) -> Any:
        response = browser.post(
            reverse("account_login"), {"login": alice.email, "password": PASSWORD}
        )
        assert response.status_code == 302
        assert _signed_in(browser)
        return begin(*args, **kwargs)

    monkeypatch.setattr(webauthn_views.auth, "begin_authentication", answered_after_the_sign_in)
    answer = late.get(reverse("mfa_login_webauthn"), HTTP_ACCEPT="application/json")
    # Django sees the session replaced while the request ran: a 400, and no cookie.
    assert answer.status_code == 400
    assert settings.SESSION_COOKIE_NAME not in answer.cookies
    for name, morsel in answer.cookies.items():
        browser.cookies[name] = morsel.value
    assert _signed_in(browser)
    assert browser.get(reverse("index")).context["user"] == alice


def test_a_challenge_fetched_first_still_signs_in_with_a_password(alice: User) -> None:
    browser = Client()
    browser.get(reverse("account_login"))
    challenge = browser.get(reverse("mfa_login_webauthn"), HTTP_ACCEPT="application/json")
    assert challenge.status_code == 200
    assert "request_options" in challenge.json()
    response = browser.post(reverse("account_login"), {"login": alice.email, "password": PASSWORD})
    assert response.status_code == 302
    assert _signed_in(browser)
