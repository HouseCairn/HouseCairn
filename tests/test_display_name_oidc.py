"""The display name taken from the sign-in provider (docs/adr/0045).

The identity provider is simulated as in tests/test_oidc_signup.py: each test builds the
sign-in allauth would receive from the provider's userinfo endpoint and runs allauth's own
login flow on it. Nothing goes to the network.

New names are imported inside the tests, so that each test fails on its own on a version
without this behaviour.
"""

import logging
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from allauth.account.middleware import AccountMiddleware
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.internal.flows.login import complete_login
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts import services
from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
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
            },
            {
                "provider_id": "school",
                "name": "School SSO",
                "client_id": "housecairn",
                "secret": "not-a-secret",
                "settings": {"server_url": "https://sso.example.org"},
            },
        ]
    }
}
LOGGER = "housecairn.security"


@pytest.fixture(autouse=True)
def oidc_providers() -> Iterator[None]:
    with override_settings(SOCIALACCOUNT_PROVIDERS=PROVIDERS, HOUSECAIRN_OIDC_SIGNUP="open"):
        yield


def sign_in(provider: str = "company", sub: str = "sub-1", **claims: Any) -> HttpResponse:
    """A sign-in through `provider` with these userinfo claims, as allauth runs it."""
    claims.setdefault("email", "person@example.com")
    claims.setdefault("email_verified", True)
    claims["sub"] = sub

    def action(request: HttpRequest) -> HttpResponse:
        provider_obj = get_adapter().get_provider(request, provider)
        login: SocialLogin = provider_obj.sociallogin_from_response(request, {"userinfo": claims})
        response: HttpResponse = complete_login(request, login)
        return response

    request = RequestFactory().get(f"/accounts/oidc/{provider}/login/callback/")
    handler: Any = AccountMiddleware(action)
    for middleware in (MessageMiddleware, AuthenticationMiddleware, SessionMiddleware):
        handler = middleware(handler)
    response: HttpResponse = handler(request)
    return response


def link(user: User, provider: str = "company", sub: str = "sub-1", **claims: Any) -> None:
    """An identity of `provider` already linked to `user`, with the claims allauth kept."""
    SocialAccount.objects.create(
        user=user, provider=provider, uid=sub, extra_data={"userinfo": {"sub": sub, **claims}}
    )


def person() -> User:
    return User.objects.get(email="person@example.com")


@pytest.fixture
def linked(make_user: Callable[..., User]) -> User:
    """An account linked to `company`, without a display name yet."""
    user = make_user("person@example.com")
    link(user)
    return user


class TestFirstSignIn:
    @pytest.mark.parametrize(
        ("claims", "expected"),
        [
            (
                {
                    "name": "Jane Doe",
                    "given_name": "Janet",
                    "family_name": "Dee",
                    "preferred_username": "jdoe",
                    "nickname": "JJ",
                },
                "Jane Doe",
            ),
            (
                {"given_name": "Janet", "family_name": "Dee", "preferred_username": "jdoe"},
                "Janet Dee",
            ),
            ({"given_name": "Janet", "preferred_username": "jdoe"}, "Janet"),
            ({"preferred_username": "jdoe", "nickname": "JJ"}, "jdoe"),
            ({"nickname": "JJ"}, "JJ"),
        ],
    )
    def test_the_name_follows_the_order_of_the_claims(
        self, claims: dict[str, str], expected: str
    ) -> None:
        response = sign_in(**claims)
        assert response.status_code == 302
        user = person()
        assert user.display_name == expected
        assert user.display_name_source == "oidc"
        assert user.display_name_provider == "company"

    def test_no_claim_leaves_no_name(self) -> None:
        assert sign_in().status_code == 302
        user = person()
        assert (user.display_name, user.display_name_source, user.display_name_provider) == (
            "",
            "oidc",
            "",
        )

    def test_an_existing_account_without_a_name_takes_it(self, linked: User) -> None:
        assert sign_in(name="Jane Doe").status_code == 302
        linked.refresh_from_db()
        assert linked.display_name == "Jane Doe"

    def test_claims_of_the_id_token_count_too(self) -> None:
        from housecairn.accounts import provider_names

        claims = provider_names.claims_of({"id_token": {"name": "From token"}, "userinfo": {}})
        assert provider_names.name_from_claims(claims) == "From token"
        claims = provider_names.claims_of(
            {"id_token": {"name": "From token"}, "userinfo": {"name": "From userinfo"}}
        )
        assert provider_names.name_from_claims(claims) == "From userinfo"


class TestLaterSignIns:
    def test_a_changed_claim_updates_the_name(self, linked: User) -> None:
        sign_in(name="Jane Doe")
        sign_in(name="Jane Smith")
        linked.refresh_from_db()
        assert linked.display_name == "Jane Smith"
        assert linked.display_name_source == "oidc"

    def test_a_typed_name_is_never_overwritten(self, linked: User) -> None:
        sign_in(name="Jane Doe")
        services.set_display_name(linked, "Janie")
        linked.refresh_from_db()
        assert linked.display_name_source == "manual"
        sign_in(name="Jane Smith")
        linked.refresh_from_db()
        assert linked.display_name == "Janie"
        assert linked.display_name_provider == ""

    def test_the_profile_form_makes_it_manual(self, client: Client, linked: User) -> None:
        sign_in(name="Jane Doe")
        client.force_login(linked)
        client.post(reverse("profile"), {"display_name": "Janie"})
        sign_in(name="Jane Smith")
        linked.refresh_from_db()
        assert linked.display_name == "Janie"
        assert linked.display_name_source == "manual"

    def test_saving_the_same_name_keeps_it_the_provider_s(
        self, client: Client, linked: User
    ) -> None:
        sign_in(name="Jane Doe")
        client.force_login(linked)
        client.post(reverse("profile"), {"display_name": "Jane Doe"})
        sign_in(name="Jane Smith")
        linked.refresh_from_db()
        assert linked.display_name == "Jane Smith"

    def test_the_api_makes_it_manual(self, linked: User) -> None:
        sign_in(name="Jane Doe")
        api = APIClient()
        api.force_authenticate(linked)
        response = api.patch("/api/v1/me/", {"display_name": "Janie"}, format="json")
        assert response.status_code == 200
        assert response.json()["display_name_source"] == "manual"
        sign_in(name="Jane Smith")
        linked.refresh_from_db()
        assert linked.display_name == "Janie"


class TestUseTheProviderName:
    def test_the_button_gives_it_back_at_once(self, client: Client, linked: User) -> None:
        sign_in(name="Jane Doe")
        services.set_display_name(linked, "Janie")
        client.force_login(linked)
        page = client.get(reverse("profile")).content.decode()
        assert "Use the provider&#x27;s name" in page or "Use the provider's name" in page
        response = client.post(reverse("profile"), {"use_provider": "1"})
        assert response.status_code == 302
        linked.refresh_from_db()
        assert linked.display_name_source == "oidc"
        assert linked.display_name == "Jane Doe"
        page = client.get(reverse("profile")).content.decode()
        assert "Taken from Company SSO." in page
        # From now on the provider follows again.
        sign_in(name="Jane Smith")
        linked.refresh_from_db()
        assert linked.display_name == "Jane Smith"

    def test_without_a_kept_claim_it_waits_for_the_next_sign_in(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        user = make_user("person@example.com")
        link(user)  # no name among the claims kept
        services.set_display_name(user, "Janie")
        client.force_login(user)
        client.post(reverse("profile"), {"use_provider": "1"})
        user.refresh_from_db()
        assert user.display_name_source == "oidc"
        assert user.display_name == "Janie"
        sign_in(name="Jane Doe")
        user.refresh_from_db()
        assert user.display_name == "Jane Doe"

    def test_by_the_api(self, linked: User) -> None:
        sign_in(name="Jane Doe")
        services.set_display_name(linked, "Janie")
        api = APIClient()
        api.force_authenticate(linked)
        response = api.patch("/api/v1/me/", {"display_name_source": "oidc"}, format="json")
        assert response.status_code == 200
        body = response.json()
        assert body["display_name"] == "Jane Doe"
        assert body["display_name_source"] == "oidc"
        assert body["display_name_provider"] == "company"

    def test_an_api_token_cannot(self, alice: User, alice_home: Home) -> None:
        link(alice, sub="sub-alice", name="Alice Provider")
        services.set_display_name(alice, "Ally")
        _token, raw = token_services.issue_token(
            alice,
            name="t",
            scopes=["read", "write"],
            homes=[alice_home],
            lifetime=timedelta(days=1),
        )
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        response = api.patch("/api/v1/me/", {"display_name_source": "oidc"}, format="json")
        assert response.status_code == 403
        alice.refresh_from_db()
        assert alice.display_name == "Ally"
        assert alice.display_name_source == "manual"

    def test_no_button_without_a_provider(self, client: Client, alice: User) -> None:
        services.set_display_name(alice, "Ally")
        client.force_login(alice)
        page = client.get(reverse("profile")).content.decode()
        assert "use_provider" not in page
        client.post(reverse("profile"), {"use_provider": "1"})
        alice.refresh_from_db()
        assert alice.display_name_source == "manual"


TRAPS = {
    "html": "<b>Jane</b>",
    "script": "<script>alert(1)</script>",
    "invisible": "\u200b\u2060\u3164",
    "address": "jane@example.com",
    "full-width address": "jane\uff20example.com",
    "too long": "x" * 500,
    "empty": "",
    "spaces": "   ",
}


class TestTrappedClaims:
    @pytest.mark.parametrize("trap", TRAPS.values(), ids=TRAPS.keys())
    def test_it_is_ignored_and_the_sign_in_goes_on(
        self, linked: User, trap: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        sign_in(name="Jane Doe")
        with caplog.at_level(logging.INFO, logger=LOGGER):
            response = sign_in(name=trap)
        assert response.status_code == 302
        linked.refresh_from_db()
        assert linked.display_name == "Jane Doe"
        lines = [r.getMessage() for r in caplog.records if "Display name" in r.getMessage()]
        assert len(lines) == 1
        if trap.strip():
            assert trap not in lines[0]

    def test_the_next_claim_is_taken(self, linked: User) -> None:
        sign_in(name="jane@example.com", given_name="Jane", family_name="Doe")
        linked.refresh_from_db()
        assert linked.display_name == "Jane Doe"

    def test_without_a_previous_name_there_stays_none(
        self, linked: User, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger=LOGGER):
            assert sign_in(name="x" * 500, nickname="@jd").status_code == 302
        linked.refresh_from_db()
        assert linked.display_name == ""
        lines = sorted(r.getMessage() for r in caplog.records if "Display name" in r.getMessage())
        assert lines == [
            "Display name from the sign-in provider ignored (contains @): nickname",
            "Display name from the sign-in provider ignored (too long): name",
        ]

    def test_a_claim_that_is_not_text_is_ignored(
        self, linked: User, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger=LOGGER):
            assert sign_in(name={"first": "Jane"}, nickname=["JJ"]).status_code == 302
        linked.refresh_from_db()
        assert linked.display_name == ""
        lines = [r.getMessage() for r in caplog.records if "Display name" in r.getMessage()]
        # One line per reason, naming both claims.
        assert lines == [
            "Display name from the sign-in provider ignored (not text): name, nickname"
        ]

    def test_fillers_and_spaces_are_trimmed(self, linked: User) -> None:
        sign_in(name="  Jane\u3164 ")
        linked.refresh_from_db()
        assert linked.display_name == "Jane"

    def test_the_page_escapes_what_was_taken(self, client: Client, linked: User) -> None:
        sign_in(name="Jane & Co")
        client.force_login(linked)
        page = client.get(reverse("profile")).content.decode()
        assert "Jane &amp; Co" in page


class TestWhereSsoDoesNotApply:
    def test_a_local_account_is_unchanged(self, client: Client, alice: User) -> None:
        client.force_login(alice)
        client.post(reverse("profile"), {"display_name": "Ally"})
        alice.refresh_from_db()
        assert alice.display_name == "Ally"
        assert alice.display_name_source == "manual"
        page = client.get(reverse("profile")).content.decode()
        assert "display-name-source" not in page
        # A sign-in with a password changes nothing.
        assert client.login(email="alice@example.com", password="correct-horse-battery-staple")
        alice.refresh_from_db()
        assert alice.display_name == "Ally"

    def test_a_local_account_without_name_stays_without(self, alice: User) -> None:
        client = Client()
        assert client.login(email="alice@example.com", password="correct-horse-battery-staple")
        alice.refresh_from_db()
        assert alice.display_name == ""
        assert alice.display_name_provider == ""


class TestTwoProviders:
    def test_the_provider_used_gives_the_name(self, linked: User, client: Client) -> None:
        link(linked, provider="school", sub="sub-2")
        sign_in(name="Jane Doe")
        linked.refresh_from_db()
        assert (linked.display_name, linked.display_name_provider) == ("Jane Doe", "company")
        sign_in(provider="school", sub="sub-2", name="J. Doe")
        linked.refresh_from_db()
        assert (linked.display_name, linked.display_name_provider) == ("J. Doe", "school")
        client.force_login(linked)
        assert "Taken from School SSO." in client.get(reverse("profile")).content.decode()

    def test_a_provider_whose_claims_are_refused_keeps_the_other_s(self, linked: User) -> None:
        link(linked, provider="school", sub="sub-2")
        sign_in(name="Jane Doe")
        sign_in(provider="school", sub="sub-2", name="<i>x</i>")
        linked.refresh_from_db()
        assert (linked.display_name, linked.display_name_provider) == ("Jane Doe", "company")


class TestNothingMoreIsStored:
    def test_the_account_keeps_no_claim(self, linked: User) -> None:
        sign_in(name="Jane Doe", email="other@example.com", picture="https://example.com/p.png")
        linked.refresh_from_db()
        assert linked.display_name == "Jane Doe"
        assert linked.email == "person@example.com"
        values = {str(getattr(linked, f.attname)) for f in User._meta.concrete_fields}
        assert "https://example.com/p.png" not in values
        assert "other@example.com" not in values

    def test_the_admin_shows_the_source_read_only(self, linked: User) -> None:
        from django.contrib import admin

        model_admin = admin.site._registry[User]
        assert "display_name_source" in model_admin.readonly_fields
        assert "display_name_provider" not in model_admin.get_fields(None)  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_the_migration_marks_typed_names_and_goes_back() -> None:
    def apps_at(target: str) -> Any:
        call_command("migrate", "accounts", target, verbosity=0)
        return MigrationExecutor(connection).loader.project_state([("accounts", target)]).apps

    try:
        apps = apps_at("0004_user_display_name")
        old = apps.get_model("accounts", "User")
        old.objects.create(email="typed@example.com", display_name="Janie")
        old.objects.create(email="none@example.com")
        apps = apps_at("0005_display_name_source")
        users = apps.get_model("accounts", "User").objects
        assert dict(users.values_list("email", "display_name_source")) == {
            "typed@example.com": "manual",
            "none@example.com": "oidc",
        }
        apps = apps_at("0004_user_display_name")
        users = apps.get_model("accounts", "User").objects
        assert dict(users.values_list("email", "display_name")) == {
            "typed@example.com": "Janie",
            "none@example.com": "",
        }
        apps = apps_at("0005_display_name_source")
        users = apps.get_model("accounts", "User").objects
        assert users.get(email="typed@example.com").display_name_source == "manual"
    finally:
        call_command("migrate", verbosity=0)


@pytest.mark.django_db(transaction=True)
def test_after_the_migration_a_typed_name_stays_and_an_empty_one_is_taken() -> None:
    try:
        call_command("migrate", "accounts", "0004_user_display_name", verbosity=0)
        state = MigrationExecutor(connection).loader.project_state(
            [("accounts", "0004_user_display_name")]
        )
        old = state.apps.get_model("accounts", "User")
        typed = old.objects.create(email="typed@example.com", display_name="Janie")
        empty = old.objects.create(email="person@example.com")
        call_command("migrate", verbosity=0)
        link(User.objects.get(pk=typed.pk), sub="sub-typed")
        link(User.objects.get(pk=empty.pk), sub="sub-1")
        sign_in(sub="sub-typed", email="typed@example.com", name="Jane Typed")
        sign_in(name="Jane Doe")
        assert User.objects.get(pk=typed.pk).display_name == "Janie"
        assert User.objects.get(pk=empty.pk).display_name == "Jane Doe"
    finally:
        call_command("migrate", verbosity=0)
