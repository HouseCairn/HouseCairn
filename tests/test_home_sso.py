"""A home that requires a sign-in provider (docs/adr/0021), and who sees nothing of a home."""

from collections.abc import Callable
from typing import Any

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import Client, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes import services
from housecairn.homes.models import Home, Membership, Role

pytestmark = pytest.mark.django_db

PROVIDERS = {
    "openid_connect": {
        "APPS": [
            {
                "provider_id": provider_id,
                "name": name,
                "client_id": "housecairn",
                "secret": "not-a-secret",
                "settings": {"server_url": "https://id.example.com"},
            }
            for provider_id, name in (("company", "Company SSO"), ("other", "Other SSO"))
        ]
    }
}


@pytest.fixture(autouse=True)
def _providers(settings: Any) -> None:
    settings.SOCIALACCOUNT_PROVIDERS = PROVIDERS


def signed_in_through(client: Client, user: User, provider: str | None) -> None:
    """Sign in as django-allauth would, recording the provider when there is one."""
    client.force_login(user)
    session = client.session
    session["account_authentication_methods_user"] = str(user.pk)
    record = {"method": "password", "at": 0.0}
    if provider:
        record = {"method": "socialaccount", "provider": provider, "uid": "x", "at": 0.0}
    session["account_authentication_methods"] = [record]
    session.save()


@pytest.fixture
def locked_home(alice_home: Home) -> Home:
    alice_home.required_provider = "company"
    alice_home.save()
    return alice_home


class TestRequirement:
    def test_password_session_is_refused_everywhere(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        signed_in_through(client, alice, None)
        kwargs = {"home_id": locked_home.id}
        detail = client.get(reverse("homes:detail", kwargs=kwargs))
        assert detail.status_code == 403
        assert "Continue with Company SSO" in detail.text
        assert "/accounts/oidc/company/login/" in detail.text
        assert client.get(reverse("homes:household", kwargs=kwargs)).status_code == 403
        invite = client.post(
            reverse("homes:invite", kwargs=kwargs), {"email": "x@example.com", "role": "owner"}
        )
        assert invite.status_code == 403
        assert not locked_home.invitations.exists()

    def test_the_list_shows_the_home_locked(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        signed_in_through(client, alice, None)
        html = client.get(reverse("homes:list")).text
        assert locked_home.name in html
        assert "Company SSO required" in html

    def test_another_provider_does_not_open_it(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        signed_in_through(client, alice, "other")
        response = client.get(reverse("homes:detail", kwargs={"home_id": locked_home.id}))
        assert response.status_code == 403

    def test_the_required_provider_opens_it(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        signed_in_through(client, alice, "company")
        kwargs = {"home_id": locked_home.id}
        assert client.get(reverse("homes:detail", kwargs=kwargs)).status_code == 200
        assert client.get(reverse("homes:household", kwargs=kwargs)).status_code == 200
        assert "required" not in client.get(reverse("homes:list")).text

    def test_api_session(self, client: Client, alice: User, locked_home: Home) -> None:
        signed_in_through(client, alice, None)
        url = reverse("api-v1:home-detail", kwargs={"home_id": locked_home.id})
        response = client.get(url)
        assert response.status_code == 403
        assert response.json()["code"] == "sso_required"
        assert response.json()["provider"] == "company"
        listed = client.get(reverse("api-v1:home-list")).json()["results"]
        assert listed[0]["locked"] is True
        members = reverse("api-v1:home-member-list", kwargs={"home_id": locked_home.id})
        assert client.get(members).status_code == 403
        signed_in_through(client, alice, "company")
        assert client.get(url).status_code == 200
        assert client.get(members).status_code == 200

    def test_api_token_never_opens_it(
        self, api_client: APIClient, alice: User, locked_home: Home
    ) -> None:
        _token, raw = token_services.issue_token(
            alice, name="ha", scopes=["read", "events"], homes=[locked_home]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        detail = api_client.get(reverse("api-v1:home-detail", kwargs={"home_id": locked_home.id}))
        assert detail.status_code == 403
        events = reverse("api-v1:home-events", kwargs={"home_id": locked_home.id})
        assert api_client.post(events, {"kind": "battery_low"}).status_code == 403

    def test_other_homes_stay_open(self, client: Client, alice: User, locked_home: Home) -> None:
        other = services.create_home(alice, name="Cottage")
        signed_in_through(client, alice, None)
        assert client.get(reverse("homes:detail", kwargs={"home_id": other.id})).status_code == 200


class TestSettingTheRequirement:
    DECLARED = ("company", "other")

    def test_owner_sets_it_from_a_session_through_that_provider(
        self, alice: User, alice_home: Home
    ) -> None:
        services.set_required_provider(
            alice,
            alice_home,
            "company",
            declared=self.DECLARED,
            signed_in_with=frozenset({"company"}),
        )
        assert alice_home.required_provider == "company"
        services.set_required_provider(
            alice, alice_home, "", declared=self.DECLARED, signed_in_with=frozenset({"company"})
        )
        assert alice_home.required_provider == ""

    def test_not_from_a_password_session(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValidationError):
            services.set_required_provider(
                alice, alice_home, "company", declared=self.DECLARED, signed_in_with=frozenset()
            )

    def test_only_a_declared_provider(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValidationError):
            services.set_required_provider(
                alice,
                alice_home,
                "rogue",
                declared=self.DECLARED,
                signed_in_with=frozenset({"rogue"}),
            )

    def test_only_an_owner(
        self, bob: User, alice_home: Home, add_member: Callable[..., Membership]
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        from django.core.exceptions import PermissionDenied

        with pytest.raises(PermissionDenied):
            services.set_required_provider(
                bob, alice_home, "", declared=self.DECLARED, signed_in_with=frozenset({"company"})
            )

    def test_web_form(self, client: Client, alice: User, alice_home: Home) -> None:
        url = reverse("homes:required-provider", kwargs={"home_id": alice_home.id})
        signed_in_through(client, alice, None)
        response = client.post(url, {"provider": "company"}, follow=True)
        assert "Sign in through this provider first" in response.text
        alice_home.refresh_from_db()
        assert alice_home.required_provider == ""
        signed_in_through(client, alice, "company")
        page = client.get(reverse("homes:household", kwargs={"home_id": alice_home.id})).text
        assert "Company SSO" in page
        client.post(url, {"provider": "company"})
        alice_home.refresh_from_db()
        assert alice_home.required_provider == "company"

    def test_api(self, client: Client, alice: User, alice_home: Home) -> None:
        url = reverse("api-v1:home-detail", kwargs={"home_id": alice_home.id})
        signed_in_through(client, alice, None)
        refused = client.patch(
            url, {"required_provider": "company"}, content_type="application/json"
        )
        assert refused.status_code == 400
        signed_in_through(client, alice, "company")
        accepted = client.patch(
            url, {"required_provider": "company"}, content_type="application/json"
        )
        assert accepted.status_code == 200
        assert accepted.json()["required_provider"] == "company"

    def test_no_section_without_a_declared_provider(
        self, client: Client, alice: User, alice_home: Home
    ) -> None:
        with override_settings(SOCIALACCOUNT_PROVIDERS={}):
            client.force_login(alice)
            page = client.get(reverse("homes:household", kwargs={"home_id": alice_home.id})).text
        assert reverse("homes:required-provider", kwargs={"home_id": alice_home.id}) not in page


def test_no_account_is_taken_over_by_a_matching_address() -> None:
    # An identity from a provider never signs in to, nor links itself to, an
    # account because the provider claims the same address (docs/adr/0021).
    assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION is False
    assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT is False


class TestIsolation:
    """A member of home A, the instance administrator and an API token see nothing of B."""

    @pytest.fixture
    def admin(self, make_user: Callable[..., User]) -> User:
        return make_user("admin@example.com", is_staff=True, is_superuser=True)

    def web_urls(self, home: Home) -> list[str]:
        owner = Membership.objects.get(home=home)
        kwargs = {"home_id": home.id}
        return [
            reverse("homes:detail", kwargs=kwargs),
            reverse("homes:household", kwargs=kwargs),
            reverse("homes:member", kwargs={**kwargs, "member_id": owner.id}),
        ]

    def api_urls(self, home: Home) -> list[str]:
        kwargs = {"home_id": home.id}
        return [
            reverse("api-v1:home-detail", kwargs=kwargs),
            reverse("api-v1:home-member-list", kwargs=kwargs),
            reverse("api-v1:home-invitation-list", kwargs=kwargs),
        ]

    @pytest.mark.parametrize("who", ["member_of_a", "admin"])
    def test_web_and_session_api(
        self,
        client: Client,
        alice: User,
        admin: User,
        alice_home: Home,
        bob_home: Home,
        who: str,
    ) -> None:
        client.force_login(alice if who == "member_of_a" else admin)
        for url in self.web_urls(bob_home) + self.api_urls(bob_home):
            response = client.get(url)
            assert response.status_code == 404, url
            assert bob_home.name not in response.text
        assert bob_home.name not in client.get(reverse("homes:list")).text
        listed = client.get(reverse("api-v1:home-list")).json()["results"]
        assert str(bob_home.id) not in {h["id"] for h in listed}

    def test_api_token(
        self, api_client: APIClient, alice: User, alice_home: Home, bob_home: Home
    ) -> None:
        _token, raw = token_services.issue_token(
            alice, name="all", scopes=["read", "write"], homes=[alice_home]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        for url in self.api_urls(bob_home):
            assert api_client.get(url).status_code == 404, url
        listed = api_client.get(reverse("api-v1:home-list")).json()["results"]
        assert [h["id"] for h in listed] == [str(alice_home.id)]
