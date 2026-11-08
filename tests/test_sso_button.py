"""The single-sign-on button goes straight to the provider, with no confirmation page.

allauth answers a GET on a provider's login address with a confirmation page ("You
are about to sign in using a third-party account") and starts the sign-in only for a
POST. The buttons are therefore forms posted with the CSRF token, and
SOCIALACCOUNT_LOGIN_ON_GET stays off. The provider's discovery document is
simulated: nothing goes to the network.
"""

import re
from collections.abc import Iterator
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import pytest
from allauth.socialaccount.providers.openid_connect.views import OpenIDConnectOAuth2Adapter
from django.conf import settings
from django.test import Client, override_settings
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes.models import Home

pytestmark = pytest.mark.django_db

PROVIDERS = {
    "openid_connect": {
        "APPS": [
            {
                "provider_id": "company",
                "name": "Company SSO",
                "client_id": "housecairn",
                "secret": "not-a-secret",
                "settings": {"server_url": "https://id.example.com"},
            }
        ]
    }
}
DISCOVERY = {
    "authorization_endpoint": "https://id.example.com/authorize",
    "token_endpoint": "https://id.example.com/token",
    "userinfo_endpoint": "https://id.example.com/userinfo",
}
LOGIN_URL = "/accounts/oidc/company/login/"
FORM = re.compile(
    r'<form method="post" action="([^"]+)">\s*<input[^>]*csrfmiddlewaretoken[^>]*>\s*'
    r'<button type="submit"[^>]*>Continue with Company SSO</button>'
)


@pytest.fixture(autouse=True)
def provider() -> Iterator[None]:
    with (
        override_settings(SOCIALACCOUNT_PROVIDERS=PROVIDERS),
        mock.patch.object(
            OpenIDConnectOAuth2Adapter,
            "openid_config",
            new_callable=mock.PropertyMock,
            return_value=DISCOVERY,
        ),
    ):
        yield


def stashed_states(client: Client) -> str:
    return str(client.session.get("socialaccount_states", {}))


def action_of(html: str) -> str:
    found = FORM.search(html)
    assert found, "the provider button is a POST form with a CSRF token"
    return found.group(1).replace("&amp;", "&")


class TestSignInPage:
    def test_login_on_get_stays_off(self) -> None:
        assert not getattr(settings, "SOCIALACCOUNT_LOGIN_ON_GET", False)

    def test_the_button_is_a_form_to_the_provider_login(self, client: Client) -> None:
        html = client.get(reverse("account_login")).text
        assert action_of(html).startswith(LOGIN_URL)
        assert f'href="{LOGIN_URL}' not in html

    def test_one_post_goes_to_the_provider(self, client: Client) -> None:
        response = client.post(action_of(client.get(reverse("account_login")).text))
        assert response.status_code == 302
        target = urlsplit(response["Location"])
        assert (
            f"{target.scheme}://{target.netloc}{target.path}" == DISCOVERY["authorization_endpoint"]
        )
        assert parse_qs(target.query)["client_id"] == ["housecairn"]
        assert "You are about to sign in" not in response.text

    def test_the_post_needs_the_csrf_token(self) -> None:
        strict = Client(enforce_csrf_checks=True)
        assert strict.post(LOGIN_URL, {"process": "login"}).status_code == 403
        assert "socialaccount_states" not in strict.session

    def test_the_browser_posts_the_token_the_page_gave(self) -> None:
        strict = Client(enforce_csrf_checks=True)
        page = strict.get(reverse("account_login"))
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.text)
        assert token
        response = strict.post(action_of(page.text), {"csrfmiddlewaretoken": token.group(1)})
        assert response.status_code == 302
        assert response["Location"].startswith(DISCOVERY["authorization_endpoint"])

    def test_a_get_starts_nothing(self, client: Client) -> None:
        response = client.get(f"{LOGIN_URL}?process=login")
        assert response.status_code == 200
        assert "Location" not in response
        assert "You are about to sign in" in response.text
        assert stashed_states(client) == "{}"

    def test_next_is_kept(self, client: Client) -> None:
        response = client.post(f"{LOGIN_URL}?process=login&next=/h/")
        assert response.status_code == 302
        assert "'/h/'" in stashed_states(client)


class TestHomeThatRequiresTheProvider:
    @pytest.fixture
    def locked_home(self, alice_home: Home) -> Home:
        alice_home.required_provider = "company"
        alice_home.save()
        return alice_home

    def test_the_button_posts_and_keeps_the_home(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        client.force_login(alice)
        page = client.get(reverse("homes:detail", kwargs={"home_id": locked_home.id}))
        assert page.status_code == 403
        action = action_of(page.text)
        assert action.startswith(LOGIN_URL)
        assert f"next=/h/{locked_home.id}/" in action
        response = client.post(action)
        assert response.status_code == 302
        assert response["Location"].startswith(DISCOVERY["authorization_endpoint"])
        assert f"/h/{locked_home.id}/" in stashed_states(client)
