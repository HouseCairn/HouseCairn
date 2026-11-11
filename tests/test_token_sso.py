"""API tokens of a home that requires a sign-in provider (docs/adr/0057).

A token is bound to such a home only from a session signed in through its provider; it
records that provider and then opens the home by the API, as long as the home requires
that provider or nothing. Everything that cuts a token still cuts it.
"""

import json
from datetime import timedelta
from typing import Any

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services
from housecairn.apitokens.models import ApiToken
from housecairn.homes import services as home_services
from housecairn.homes.models import Home, Membership, Role
from tests.test_home_sso import PROVIDERS, signed_in_through

pytestmark = pytest.mark.django_db

LIST = "api-v1:token-list"


@pytest.fixture(autouse=True)
def _providers(settings: Any) -> None:
    settings.SOCIALACCOUNT_PROVIDERS = PROVIDERS


@pytest.fixture
def locked_home(alice_home: Home) -> Home:
    alice_home.required_provider = "company"
    alice_home.save()
    return alice_home


def bearer(raw: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def home_url(home: Home) -> str:
    return reverse("api-v1:home-detail", kwargs={"home_id": home.id})


def api_create(client: Client, *homes: Home, **extra: Any) -> Any:
    body = {"name": "Home Assistant", "homes": [str(h.id) for h in homes], **extra}
    return client.post(reverse(LIST), json.dumps(body), content_type="application/json")


def form_post(client: Client, *homes: Home) -> Any:
    return client.post(
        reverse("api-tokens:new"),
        {
            "name": "Home Assistant",
            "scopes": ["read", "write"],
            "homes": [str(h.id) for h in homes],
            "lifetime_days": "90",
        },
    )


def secret_of(page: Any) -> str:
    body: str = page.content.decode()
    return body.split('id="token-value"', 1)[1].split('value="', 1)[1].split('"', 1)[0]


def oidc_token(client: Client, alice: User, home: Home) -> str:
    signed_in_through(client, alice, "company")
    response = api_create(client, home, scopes=["read", "write", "events"])
    assert response.status_code == 201, response.content
    raw: str = response.json()["token"]
    return raw


class TestBindingFromASessionThroughTheProvider:
    def test_the_api_binds_it_and_the_token_opens_the_home(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        raw = oidc_token(client, alice, locked_home)
        assert ApiToken.objects.get().signed_in_provider == "company"
        api = bearer(raw)
        assert api.get(home_url(locked_home)).status_code == 200
        listed = api.get(reverse("api-v1:home-list")).json()["results"]
        assert [(h["id"], h["locked"]) for h in listed] == [(str(locked_home.id), False)]
        events = reverse("api-v1:home-events", kwargs={"home_id": locked_home.id})
        assert api.post(events, {"kind": "battery_low"}, format="json").status_code == 202

    def test_the_screen_binds_it_and_the_token_opens_the_home(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        signed_in_through(client, alice, "company")
        page = client.get(reverse("api-tokens:new")).content.decode()
        box = page.split(f'value="{locked_home.id}"', 1)[1].split(">", 1)[0]
        assert "disabled" not in box
        assert "checked" in box  # the only home, ticked
        response = form_post(client, locked_home)
        assert response.status_code == 200
        raw = secret_of(response)
        assert ApiToken.objects.get().signed_in_provider == "company"
        assert bearer(raw).get(home_url(locked_home)).status_code == 200

    def test_the_token_keeps_at_most_the_role_of_the_person(
        self, client: Client, bob: User, locked_home: Home
    ) -> None:
        Membership.objects.create(home=locked_home, user=bob, role=Role.READ_ONLY)
        raw = oidc_token(client, bob, locked_home)
        api = bearer(raw)
        assert api.get(home_url(locked_home)).status_code == 200
        renamed = api.patch(home_url(locked_home), {"name": "Mine"}, format="json")
        assert renamed.status_code == 403
        locked_home.refresh_from_db()
        assert locked_home.name == "Main house"

    def test_another_provider_does_not_bind_it(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        signed_in_through(client, alice, "other")
        response = api_create(client, locked_home)
        assert response.status_code == 403
        assert response.json()["code"] == "sso_required"
        assert not ApiToken.objects.exists()

    def test_homes_of_two_providers_take_two_tokens(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        cottage = home_services.create_home(alice, name="Cottage")
        Home.objects.filter(pk=cottage.pk).update(required_provider="other")
        client.force_login(alice)
        session = client.session
        session["account_authentication_methods_user"] = str(alice.pk)
        session["account_authentication_methods"] = [
            {"method": "socialaccount", "provider": p, "uid": "x", "at": 0.0}
            for p in ("company", "other")
        ]
        session.save()
        response = api_create(client, locked_home, cottage)
        assert response.status_code == 400
        assert not ApiToken.objects.exists()
        assert api_create(client, locked_home).status_code == 201
        assert api_create(client, cottage).status_code == 201


class TestAPasswordSessionCannotBindIt:
    def test_the_form_lists_the_home_disabled_with_the_way_to_unlock_it(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        signed_in_through(client, alice, None)
        listing = client.get(reverse("api-tokens:list")).content.decode()
        assert reverse("api-tokens:new") in listing
        assert "You have no home" not in listing
        page = client.get(reverse("api-tokens:new")).content.decode()
        box = page.split(f'value="{locked_home.id}"', 1)[1].split(">", 1)[0]
        assert "disabled" in box
        assert "checked" not in box
        assert "after signing in through Company SSO" in page
        assert 'form="sso-continue-company"' in page
        login = reverse("openid_connect_login", kwargs={"provider_id": "company"})
        target = page.split('id="sso-continue-company"', 1)[1].split(">", 1)[0]
        assert f'action="{login}?process=login&amp;next={reverse("api-tokens:new")}"' in target

    def test_a_forged_form_is_refused(self, client: Client, alice: User, locked_home: Home) -> None:
        signed_in_through(client, alice, None)
        response = form_post(client, locked_home)
        assert response.status_code == 200
        assert "opens only after signing in through Company SSO" in response.content.decode()
        assert not ApiToken.objects.exists()

    def test_a_forged_api_request_is_refused(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        signed_in_through(client, alice, None)
        response = api_create(client, locked_home)
        assert response.status_code == 403
        assert response.json() == {
            "detail": "This home requires signing in through Company SSO.",
            "code": "sso_required",
            "provider": "company",
        }
        assert not ApiToken.objects.exists()

    def test_a_provider_no_longer_offered_is_said_so(
        self, client: Client, alice: User, alice_home: Home
    ) -> None:
        Home.objects.filter(pk=alice_home.pk).update(required_provider="gone")
        signed_in_through(client, alice, None)
        page = client.get(reverse("api-tokens:new")).content.decode()
        assert "no longer offers" in page
        assert "sso-continue-gone" not in page


class TestWhatCutsTheToken:
    def test_a_new_required_provider_cuts_it_and_lifting_the_rule_does_not(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        raw = oidc_token(client, alice, locked_home)
        api = bearer(raw)
        Home.objects.filter(pk=locked_home.pk).update(required_provider="other")
        refused = api.get(home_url(locked_home))
        assert refused.status_code == 403
        assert refused.json()["code"] == "sso_required"
        assert refused.json()["provider"] == "other"
        Home.objects.filter(pk=locked_home.pk).update(required_provider="company")
        assert api.get(home_url(locked_home)).status_code == 200
        Home.objects.filter(pk=locked_home.pk).update(required_provider="")
        assert api.get(home_url(locked_home)).status_code == 200

    def test_a_removed_member_loses_the_home(
        self, client: Client, alice: User, bob: User, locked_home: Home
    ) -> None:
        membership = Membership.objects.create(home=locked_home, user=bob, role=Role.MEMBER)
        raw = oidc_token(client, bob, locked_home)
        api = bearer(raw)
        assert api.get(home_url(locked_home)).status_code == 200
        home_services.remove_member(alice, membership)
        assert api.get(home_url(locked_home)).status_code == 404

    def test_a_disabled_account_loses_everything(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        raw = oidc_token(client, alice, locked_home)
        User.objects.filter(pk=alice.pk).update(is_active=False)
        assert bearer(raw).get(home_url(locked_home)).status_code == 401

    def test_expiry_and_revocation(self, client: Client, alice: User, locked_home: Home) -> None:
        raw = oidc_token(client, alice, locked_home)
        token = ApiToken.objects.get()
        ApiToken.objects.filter(pk=token.pk).update(expires_at=timezone.now() - timedelta(1))
        assert bearer(raw).get(home_url(locked_home)).status_code == 401
        ApiToken.objects.filter(pk=token.pk).update(expires_at=timezone.now() + timedelta(1))
        assert bearer(raw).get(home_url(locked_home)).status_code == 200
        services.revoke_token(alice, token)
        assert bearer(raw).get(home_url(locked_home)).status_code == 401


class TestHomesWithoutARequirement:
    def test_a_password_session_binds_them_as_before(
        self, client: Client, alice: User, alice_home: Home
    ) -> None:
        signed_in_through(client, alice, None)
        page = client.get(reverse("api-tokens:new")).content.decode()
        assert "disabled" not in page.split(f'value="{alice_home.id}"', 1)[1].split(">", 1)[0]
        assert "sso-continue" not in page
        response = api_create(client, alice_home)
        assert response.status_code == 201
        assert ApiToken.objects.get().signed_in_provider == ""
        assert bearer(response.json()["token"]).get(home_url(alice_home)).status_code == 200

    def test_a_session_through_a_provider_records_nothing_for_them(
        self, client: Client, alice: User, alice_home: Home
    ) -> None:
        # Recorded only when a home of the token requires it: a requirement set later
        # cuts the token, as it did before.
        signed_in_through(client, alice, "company")
        raw = api_create(client, alice_home).json()["token"]
        assert ApiToken.objects.get().signed_in_provider == ""
        Home.objects.filter(pk=alice_home.pk).update(required_provider="company")
        assert bearer(raw).get(home_url(alice_home)).status_code == 403

    def test_mixed_with_a_home_that_requires_the_provider(
        self, client: Client, alice: User, locked_home: Home
    ) -> None:
        cottage = home_services.create_home(alice, name="Cottage")
        signed_in_through(client, alice, "company")
        raw = api_create(client, locked_home, cottage).json()["token"]
        api = bearer(raw)
        assert api.get(home_url(locked_home)).status_code == 200
        assert api.get(home_url(cottage)).status_code == 200

    def test_without_any_home_the_list_says_why_there_is_no_button(
        self, client: Client, alice: User
    ) -> None:
        signed_in_through(client, alice, None)
        page = client.get(reverse("api-tokens:list")).content.decode()
        assert reverse("api-tokens:new") not in page
        assert "You have no home yet" in page


@pytest.mark.django_db(transaction=True)
def test_the_migration_adds_the_field_and_is_reversible() -> None:
    def apps_at(name: str) -> Any:
        call_command("migrate", "apitokens", name, verbosity=0)
        return MigrationExecutor(connection).loader.project_state([("apitokens", name)]).apps

    try:
        # The account comes from the current model: only `apitokens` goes back in time.
        user = User.objects.create(email="old@example.com")
        apps = apps_at("0001_initial")
        apps.get_model("apitokens", "ApiToken").objects.create(
            user_id=user.pk, name="old", prefix="hc_abc", digest="0" * 64, scopes=["read"]
        )
        apps = apps_at("0002_apitoken_signed_in_provider")
        token = apps.get_model("apitokens", "ApiToken").objects.get()
        assert token.signed_in_provider == ""
        token.signed_in_provider = "company"
        token.save()
        apps = apps_at("0001_initial")
        assert apps.get_model("apitokens", "ApiToken").objects.get().name == "old"
    finally:
        call_command("migrate", verbosity=0)
