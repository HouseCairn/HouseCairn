"""Sign-in providers declared in the interface, and the last-way-to-sign-in guard (ADR 0041)."""

import ipaddress
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import pytest
from allauth.account.internal.userkit import user_id_to_str
from allauth.mfa.models import Authenticator
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.models import SocialAccount
from django.contrib.admin.sites import site as admin_site
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.admin import AccountAdminForm
from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.audit.models import AuditEvent
from housecairn.homes import services as home_services
from housecairn.homes import sso
from housecairn.homes.models import Home
from housecairn.instance import providers
from housecairn.instance.models import OidcProvider

pytestmark = pytest.mark.django_db

SECRET = "Cl1ent-S3cret-N0t-In-Any-Output"
ISSUER = "https://id.example.com/realms/company"
LIST = "instance:providers"
API_LIST = "api-v1:instance-provider-list"
API_CHECK = "api-v1:instance-provider-check"

ENV_PROVIDERS = {
    "openid_connect": {
        "OAUTH_PKCE_ENABLED": True,
        "APPS": [
            {
                "provider_id": "oidc",
                "name": "Variables SSO",
                "client_id": "housecairn",
                "secret": "env-secret-value",
                "settings": {"server_url": "https://env.example.com"},
            }
        ],
    }
}


def recent(client: Client | APIClient, user: User, *, age: float = 0) -> None:
    client.force_login(user)
    session = client.session
    session["account_authentication_methods"] = [{"method": "password", "at": time.time() - age}]
    session["account_authentication_methods_user"] = user_id_to_str(user)
    session.save()


@pytest.fixture
def admin_user(make_user: Callable[..., User]) -> User:
    return make_user("admin@example.com", is_staff=True, is_superuser=True)


@pytest.fixture
def admin_client(client: Client, admin_user: User) -> Client:
    recent(client, admin_user)
    return client


@pytest.fixture
def admin_api(api_client: APIClient, admin_user: User) -> APIClient:
    recent(api_client, admin_user)
    return api_client


def declare(actor: User, slug: str = "company", **extra: Any) -> OidcProvider:
    data: dict[str, Any] = {
        "slug": slug,
        "name": "Company SSO",
        "issuer": ISSUER,
        "client_id": "housecairn",
        "secret": SECRET,
        "enabled": True,
        **extra,
    }
    return providers.create(actor, data)


def link(user: User, slug: str) -> SocialAccount:
    account: SocialAccount = SocialAccount.objects.create(user=user, provider=slug, uid=user.email)
    return account


def sso_only(user: User, slug: str) -> User:
    user.set_unusable_password()
    user.save()
    link(user, slug)
    return user


def form(client: Client, url: str, **data: Any) -> Any:
    sent = {
        "name": "Company SSO",
        "issuer": ISSUER,
        "client_id": "housecairn",
        "pkce": "on",
        "enabled": "on",
        **data,
    }
    return client.post(url, {k: v for k, v in sent.items() if v is not False})


class TestDeclaring:
    def test_an_enabled_provider_reaches_allauth_with_its_secret_and_pkce(
        self, admin_user: User
    ) -> None:
        declare(admin_user)
        apps = get_adapter().list_apps(None)
        app = next(a for a in apps if a.provider_id == "company")
        assert app.provider == "openid_connect"
        assert app.name == "Company SSO"
        assert app.secret == SECRET
        assert app.settings == {"server_url": ISSUER, "oauth_pkce_enabled": True}
        assert get_adapter().get_app(None, "company").client_id == "housecairn"
        assert [p.id for p in sso.declared_providers()] == ["company"]

    def test_a_disabled_provider_is_not_offered(self, admin_user: User) -> None:
        declare(admin_user, enabled=False)
        assert sso.declared_providers() == []

    def test_variables_declared_later_with_the_same_identifier_win(self, admin_user: User) -> None:
        declare(admin_user, slug="oidc")
        with override_settings(SOCIALACCOUNT_PROVIDERS=ENV_PROVIDERS):
            app = get_adapter().get_app(None, "oidc")
            assert app.name == "Variables SSO"
            assert [p.id for p in sso.declared_providers()] == ["oidc"]

    def test_the_sign_in_page_shows_its_button(self, client: Client, admin_user: User) -> None:
        declare(admin_user)
        page = client.get(reverse("account_login")).text
        assert "Continue with Company SSO" in page

    @pytest.mark.parametrize(
        "slug",
        ["", "a", "Has Space", "-dash", "x" * 33, "openid_connect", "oidc"],
    )
    def test_an_identifier_must_be_free_and_well_formed(self, admin_user: User, slug: str) -> None:
        with (
            override_settings(SOCIALACCOUNT_PROVIDERS=ENV_PROVIDERS),
            pytest.raises(ValidationError) as exc,
        ):
            declare(admin_user, slug=slug)
        assert "slug" in exc.value.message_dict
        assert not OidcProvider.all_objects.exists()

    def test_an_identifier_is_never_given_twice(
        self, admin_user: User, make_user: Callable[..., User], alice_home: Home
    ) -> None:
        provider = declare(admin_user, enabled=False)
        providers.delete(admin_user, provider)
        link(make_user(), "orphan")
        alice_home.required_provider = "stale"
        alice_home.save()
        for slug in ("company", "orphan", "stale"):
            with pytest.raises(ValidationError, match="already used"):
                declare(admin_user, slug=slug)

    @pytest.mark.parametrize(
        "issuer",
        [
            "http://id.example.com",
            "https://id.example.com/?a=1",
            "https://user:pw@id.example.com",
            "https://id.example.com#x",
            "https://127.0.0.1",
            "https://[::1]",
            "https://169.254.169.254",
            "https://0.0.0.0",
            "https://id.example.com:99999",
            "ftp://id.example.com",
            "not an address",
        ],
    )
    def test_an_issuer_must_be_https_and_not_the_instance_itself(
        self, admin_user: User, issuer: str
    ) -> None:
        with pytest.raises(ValidationError) as exc:
            declare(admin_user, issuer=issuer)
        assert "issuer" in exc.value.message_dict

    def test_a_private_network_issuer_is_allowed(self, admin_user: User) -> None:
        assert declare(admin_user, issuer="https://198.18.0.5:8443/").issuer == (
            "https://198.18.0.5:8443"
        )

    def test_only_administrators(self, alice: User) -> None:
        with pytest.raises(PermissionDenied):
            declare(alice)


class TestHomesKeepTheirLink:
    def test_renaming_keeps_the_requirement_of_a_home(
        self, admin_user: User, alice_home: Home
    ) -> None:
        provider = declare(admin_user)
        alice_home.required_provider = "company"
        alice_home.save()
        providers.update(admin_user, provider, {"name": "Renamed SSO"})
        assert sso.provider_named("company").name == "Renamed SSO"
        alice_home.refresh_from_db()
        assert alice_home.required_provider == "company"
        assert not home_services.is_open(alice_home, frozenset())
        assert home_services.is_open(alice_home, frozenset({"company"}))

    def test_the_identifier_never_changes(self, admin_user: User) -> None:
        provider = declare(admin_user)
        with pytest.raises(ValidationError, match="never changes"):
            providers.update(admin_user, provider, {"slug": "other"})

    def test_a_provider_a_home_requires_cannot_be_deleted(
        self, admin_user: User, alice_home: Home
    ) -> None:
        provider = declare(admin_user)
        alice_home.required_provider = "company"
        alice_home.save()
        with pytest.raises(ValidationError, match="1 home"):
            providers.delete(admin_user, provider)
        assert OidcProvider.objects.filter(slug="company").exists()

    def test_disabling_it_follows_the_existing_way_out(
        self, admin_user: User, alice_home: Home
    ) -> None:
        from housecairn.instance import services

        provider = declare(admin_user)
        alice_home.required_provider = "company"
        alice_home.save()
        providers.update(admin_user, provider, {"enabled": False})
        declared = [p.id for p in sso.declared_providers()]
        assert "company" not in declared
        assert services.unlock_removed_providers(admin_user, declared=declared) == 1
        alice_home.refresh_from_db()
        assert alice_home.required_provider == ""


class TestTakeOver:
    def test_the_issuer_cannot_change_once_accounts_are_linked(
        self, admin_user: User, alice: User
    ) -> None:
        provider = declare(admin_user)
        providers.update(admin_user, provider, {"issuer": "https://new.example.com", "secret": "s"})
        link(alice, "company")
        with pytest.raises(ValidationError, match="another issuer could sign in"):
            providers.update(admin_user, provider, {"issuer": "https://evil.example.com"})
        provider.refresh_from_db()
        assert provider.issuer == "https://new.example.com"

    def test_an_identity_never_reaches_an_account_by_its_address(self, settings: Any) -> None:
        assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION is False
        assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT is False


EVIL = "https://idp.attacker.example"


class TestTheSecretStaysWithItsIssuer:
    """At sign-in, allauth sends the client secret to the token endpoint the issuer names.

    Another administrator who points the issuer elsewhere must not receive it.
    """

    def _app(self, slug: str = "company") -> Any:
        return next((a for a in providers.social_apps() if a.provider_id == slug), None)

    def test_a_new_issuer_clears_the_secret(self, admin_user: User) -> None:
        provider = declare(admin_user, enabled=False)
        assert providers.update(admin_user, provider, {"issuer": EVIL}) == ["secret", "issuer"]
        provider.refresh_from_db()
        assert provider.secret == ""
        assert providers.describe(provider).secret_set is False
        providers.update(admin_user, provider, {"enabled": True})
        app = self._app()
        assert (app.settings["server_url"], app.secret) == (EVIL, "")
        cleared = AuditEvent.objects.get(action="provider.secret_cleared")
        assert cleared.detail == {"provider": "company"}

    def test_an_enabled_provider_is_not_left_without_it(self, admin_user: User) -> None:
        provider = declare(admin_user)
        with pytest.raises(ValidationError, match="not kept for another issuer") as raised:
            providers.update(admin_user, provider, {"issuer": EVIL})
        assert list(raised.value.message_dict) == ["secret"]
        with pytest.raises(ValidationError, match="not kept for another issuer"):
            providers.update(admin_user, provider, {"issuer": EVIL, "secret": ""})
        provider.refresh_from_db()
        assert (provider.issuer, providers.describe(provider).secret_set) == (ISSUER, True)
        assert self._app().secret == SECRET
        assert not AuditEvent.objects.filter(action="provider.secret_cleared").exists()

    def test_a_secret_typed_again_is_kept(self, admin_user: User) -> None:
        provider = declare(admin_user)
        providers.update(admin_user, provider, {"issuer": EVIL, "secret": "new-secret"})
        assert (self._app().settings["server_url"], self._app().secret) == (EVIL, "new-secret")
        assert not AuditEvent.objects.filter(action="provider.secret_cleared").exists()

    def test_the_same_issuer_or_another_client_keeps_it(self, admin_user: User) -> None:
        provider = declare(admin_user)
        assert providers.update(admin_user, provider, {"issuer": ISSUER + "/"}) == []
        providers.update(admin_user, provider, {"client_id": "another-client"})
        assert self._app().secret == SECRET

    def test_web_and_api(self, admin_client: Client, admin_api: APIClient) -> None:
        response = form(admin_client, reverse(LIST), slug="company", secret=SECRET)
        assert response.status_code == 302
        url = reverse("instance:provider", kwargs={"slug": "company"})
        refused = form(admin_client, url, issuer=EVIL)
        assert refused.status_code == 422
        assert "not kept for another issuer" in refused.text
        assert form(admin_client, url, issuer=EVIL, enabled=False).status_code == 302
        detail = reverse("api-v1:instance-provider-detail", args=["company"])
        assert admin_api.get(detail).json()["secret_set"] is False
        assert "not set" in admin_client.get(url).text
        admin_api.patch(detail, {"issuer": ISSUER, "secret": SECRET}, format="json")
        response = admin_api.patch(detail, {"issuer": EVIL, "enabled": True}, format="json")
        assert response.status_code == 400
        assert "not kept for another issuer" in response.json()["secret"][0]
        response = admin_api.patch(detail, {"issuer": EVIL, "enabled": False}, format="json")
        assert (response.status_code, response.json()["secret_set"]) == (200, False)
        response = admin_api.patch(detail, {"issuer": ISSUER, "secret": SECRET}, format="json")
        assert (response.json()["issuer"], response.json()["secret_set"]) == (ISSUER, True)


class TestLastWayToSignIn:
    def test_an_sso_only_administrator_cannot_disable_nor_delete_its_provider(
        self, admin_user: User
    ) -> None:
        provider = declare(admin_user)
        sso_only(admin_user, "company")
        with pytest.raises(ValidationError, match="last way to sign in"):
            providers.update(admin_user, provider, {"enabled": False})
        with pytest.raises(ValidationError, match="last way to sign in"):
            providers.delete(admin_user, provider)
        provider.refresh_from_db()
        assert provider.enabled is True

    def test_nor_change_how_it_signs_in(self, admin_user: User) -> None:
        provider = declare(admin_user)
        sso_only(admin_user, "company")
        for changes in ({"client_id": "another-client"}, {"secret": "rotated"}):
            with pytest.raises(ValidationError, match="last way to sign in") as raised:
                providers.update(admin_user, provider, changes)
            assert list(raised.value.message_dict) == list(changes)
        # Its name, PKCE and the values it already has can change.
        providers.update(admin_user, provider, {"name": "New", "pkce": False})
        providers.update(admin_user, provider, {"client_id": "housecairn", "issuer": ISSUER})
        assert self._app_secret() == SECRET
        # The issuer, here of a provider no identity is linked to yet.
        SocialAccount.objects.filter(user=admin_user).delete()
        with pytest.raises(ValidationError, match="last way to sign in") as raised:
            providers.update(admin_user, provider, {"issuer": EVIL, "secret": "s"})
        assert list(raised.value.message_dict) == ["issuer"]
        provider.refresh_from_db()
        assert (provider.issuer, provider.client_id) == (ISSUER, "housecairn")
        # A disabled provider is not a way to sign in: it may change.
        other = declare(admin_user, slug="other", enabled=False)
        providers.update(admin_user, other, {"issuer": EVIL, "client_id": "c", "secret": "s"})

    def _app_secret(self) -> str:
        secret: str = get_adapter().get_app(None, "company").secret
        return secret

    def test_a_password_a_passkey_or_another_provider_is_enough(self, admin_user: User) -> None:
        first = declare(admin_user)
        second = declare(admin_user, slug="second")
        sso_only(admin_user, "company")
        link_second = link(admin_user, "second")
        providers.update(admin_user, first, {"enabled": False})
        link_second.delete()
        providers.update(admin_user, first, {"enabled": True})
        # A security key used as a second factor only is not a way to sign in.
        Authenticator.objects.create(user=admin_user, type=Authenticator.Type.WEBAUTHN, data={})
        with pytest.raises(ValidationError, match="last way to sign in"):
            providers.update(admin_user, first, {"enabled": False})
        passkey = {"credential": {"clientExtensionResults": {"credProps": {"rk": True}}}}
        Authenticator.objects.create(
            user=admin_user, type=Authenticator.Type.WEBAUTHN, data=passkey
        )
        providers.update(admin_user, first, {"enabled": False})
        assert second.enabled

    def test_a_provider_set_by_variables_counts(self, admin_user: User) -> None:
        provider = declare(admin_user)
        sso_only(admin_user, "company")
        link(admin_user, "oidc")
        with override_settings(SOCIALACCOUNT_PROVIDERS=ENV_PROVIDERS):
            providers.update(admin_user, provider, {"enabled": False})

    def test_web_and_api_refuse_it(
        self, admin_client: Client, admin_api: APIClient, admin_user: User
    ) -> None:
        provider = declare(admin_user)
        sso_only(admin_user, "company")
        recent(admin_client, admin_user)
        recent(admin_api, admin_user)
        url = reverse("instance:provider", kwargs={"slug": "company"})
        response = form(admin_client, url, enabled=False)
        assert response.status_code == 422
        assert "last way to sign in" in response.text
        response = admin_client.post(url, {"delete": "1"}, follow=True)
        assert "last way to sign in" in response.text
        detail = reverse("api-v1:instance-provider-detail", args=["company"])
        response = admin_api.patch(detail, {"enabled": False}, format="json")
        assert response.status_code == 400
        assert "last way to sign in" in response.json()["enabled"][0]
        assert admin_api.delete(detail).status_code == 400
        response = form(admin_client, url, client_id="another-client")
        assert response.status_code == 422
        assert "last way to sign in" in response.text
        response = admin_api.patch(detail, {"secret": "rotated"}, format="json")
        assert response.status_code == 400
        assert "last way to sign in" in response.json()["secret"][0]
        provider.refresh_from_db()
        assert provider.enabled
        assert provider.client_id == "housecairn"
        assert get_adapter().get_app(None, "company").secret == SECRET
        assert not provider.is_deleted


class TestLastAdministrator:
    def _form(self, user: User, **values: bool) -> AccountAdminForm:
        data = {"is_active": True, "is_staff": True, "is_superuser": True, **values}
        return AccountAdminForm({k: "on" for k, v in data.items() if v}, instance=user)

    @pytest.mark.parametrize("field", ["is_active", "is_staff", "is_superuser"])
    def test_the_only_administrator_keeps_the_role(self, admin_user: User, field: str) -> None:
        form = self._form(admin_user, **{field: False})
        assert not form.is_valid()
        assert "only administrator" in str(form.errors)

    def test_with_another_administrator_it_may_go(
        self, admin_user: User, make_user: Callable[..., User]
    ) -> None:
        make_user("second@example.com", is_staff=True, is_superuser=True)
        assert self._form(admin_user, is_active=False).is_valid()

    def test_through_the_administration_site(self, admin_client: Client, admin_user: User) -> None:
        url = reverse("admin:accounts_user_change", args=[admin_user.pk])
        response = admin_client.post(url, {"is_staff": "on", "is_superuser": "on"})
        assert response.status_code == 200
        assert "only administrator" in response.text
        admin_user.refresh_from_db()
        assert admin_user.is_active
        assert admin_site.is_registered(User)


class TestWebScreens:
    def test_the_list_shows_variables_read_only_and_the_others(
        self, admin_client: Client, admin_user: User
    ) -> None:
        declare(admin_user)
        with override_settings(SOCIALACCOUNT_PROVIDERS=ENV_PROVIDERS):
            page = admin_client.get(reverse(LIST)).text
            assert (
                admin_client.get(reverse("instance:provider", kwargs={"slug": "oidc"})).status_code
                == 404
            )
        assert "Variables SSO" in page
        assert "Set by the variables" in page
        assert "env-secret-value" not in page
        assert reverse("instance:provider", kwargs={"slug": "company"}) in page

    def test_add_then_change_then_delete(self, admin_client: Client) -> None:
        response = form(admin_client, reverse(LIST), slug="company", secret=SECRET)
        assert response.status_code == 302
        provider = OidcProvider.objects.get(slug="company")
        assert provider.enabled
        assert provider.pkce
        url = reverse("instance:provider", kwargs={"slug": "company"})
        page = admin_client.get(url).text
        assert "/accounts/oidc/company/login/callback/" in page
        assert SECRET not in page
        assert form(admin_client, url, name="New name", pkce=False).status_code == 302
        provider.refresh_from_db()
        assert (provider.name, provider.pkce) == ("New name", False)
        assert provider.secret  # an empty secret field keeps the stored one
        assert admin_client.post(url, {"delete": "1"}).status_code == 302
        assert not OidcProvider.objects.exists()
        assert OidcProvider.all_objects.get(slug="company").secret == ""

    def test_a_box_has_its_label_beside_it_and_its_help_below(
        self, admin_client: Client, admin_user: User
    ) -> None:
        declare(admin_user)
        for url in (reverse(LIST), reverse("instance:provider", kwargs={"slug": "company"})):
            page = admin_client.get(url).text
            for name in ("pkce", "enabled"):
                assert re.search(
                    rf'<p><label for="id_{name}">[^<:]+</label><input type="checkbox"[^>]*'
                    rf'id="id_{name}"[^>]*></p>\s*'
                    rf'<p class="small helptext" id="id_{name}_helptext">',
                    page,
                ), (url, name)
            # Text fields keep the layout of `form.as_p`.
            assert re.search(
                r'<p><label for="id_issuer">[^<]+</label><input[^>]*name="issuer"', page
            )

    def test_an_invalid_provider_is_refused_with_a_message(self, admin_client: Client) -> None:
        response = form(admin_client, reverse(LIST), slug="company", issuer="http://x.example")
        assert response.status_code == 422
        assert "https://" in response.text
        assert not OidcProvider.objects.exists()

    def test_changes_need_a_recent_sign_in(self, client: Client, admin_user: User) -> None:
        recent(client, admin_user, age=3600)
        response = form(client, reverse(LIST), slug="company", secret=SECRET)
        assert response["Location"].startswith(reverse("account_reauthenticate"))
        assert not OidcProvider.objects.exists()
        assert SECRET not in json.dumps(dict(client.session.items()), default=str)
        assert client.get(reverse(LIST)).status_code == 200

    def test_a_member_gets_a_404(self, client: Client, alice: User, admin_user: User) -> None:
        declare(admin_user)
        recent(client, alice)
        assert client.get(reverse(LIST)).status_code == 404
        url = reverse("instance:provider", kwargs={"slug": "company"})
        assert client.get(url).status_code == 404
        assert form(client, url, name="x").status_code == 404
        assert client.post(url, {"delete": "1"}).status_code == 404

    def test_the_overview_links_to_the_screen(self, admin_client: Client) -> None:
        assert reverse(LIST) in admin_client.get(reverse("instance:overview")).text

    def test_the_test_button_saves_nothing_and_is_rate_limited(
        self, admin_client: Client, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(providers, "discover", lambda issuer: "unreachable")
        response = form(admin_client, reverse(LIST), slug="company", test="1")
        assert response.status_code == 200
        assert "could not be reached" in response.text
        assert not OidcProvider.objects.exists()
        for _ in range(6):
            response = form(admin_client, reverse(LIST), slug="company", test="1")
        assert "Too many tests" in response.text


class TestApi:
    def test_create_read_change_delete(self, admin_api: APIClient) -> None:
        body = {"slug": "company", "name": "Company SSO", "issuer": ISSUER, "client_id": "hc"}
        response = admin_api.post(reverse(API_LIST), {**body, "secret": SECRET}, format="json")
        assert response.status_code == 201
        assert response.json()["secret_set"] is True
        assert "secret" not in response.json()
        assert response.json()["enabled"] is False
        detail = reverse("api-v1:instance-provider-detail", args=["company"])
        response = admin_api.patch(detail, {"enabled": True, "name": "N"}, format="json")
        assert response.status_code == 200
        assert (response.json()["enabled"], response.json()["name"]) == (True, "N")
        listing = admin_api.get(reverse(API_LIST)).json()["providers"]
        assert [p["slug"] for p in listing] == ["company"]
        assert admin_api.delete(detail).status_code == 204
        assert admin_api.get(detail).status_code == 404

    def test_invalid_input_is_a_400(self, admin_api: APIClient) -> None:
        for body in (
            {"slug": "company", "name": "x", "issuer": "http://x.example", "client_id": "c"},
            {"slug": "Bad Slug", "name": "x", "issuer": ISSUER, "client_id": "c"},
            {"slug": "company", "issuer": ISSUER, "client_id": "c"},
            {"slug": "company", "name": "x", "issuer": ISSUER, "client_id": "c", "extra": 1},
            {"slug": "company", "name": "x", "issuer": ISSUER, "client_id": "c", "enabled": "?"},
        ):
            assert admin_api.post(reverse(API_LIST), body, format="json").status_code == 400
        assert admin_api.post(reverse(API_LIST), [1], format="json").status_code == 400
        assert not OidcProvider.all_objects.exists()

    def test_a_provider_set_by_variables_is_listed_and_answers_409(
        self, admin_api: APIClient
    ) -> None:
        with override_settings(SOCIALACCOUNT_PROVIDERS=ENV_PROVIDERS):
            listing = admin_api.get(reverse(API_LIST)).json()["providers"]
            assert listing[0]["slug"] == "oidc"
            assert listing[0]["locked"] is True
            assert listing[0]["secret_set"] is True
            detail = reverse("api-v1:instance-provider-detail", args=["oidc"])
            assert admin_api.get(detail).json()["locked"] is True
            for response in (
                admin_api.patch(detail, {"name": "x"}, format="json"),
                admin_api.delete(detail),
            ):
                assert response.status_code == 409
                assert response.json()["code"] == "locked_by_environment"
            assert "env-secret-value" not in admin_api.get(reverse(API_LIST)).text

    def test_writes_need_a_recent_sign_in(self, api_client: APIClient, admin_user: User) -> None:
        provider = declare(admin_user)
        recent(api_client, admin_user, age=3600)
        detail = reverse("api-v1:instance-provider-detail", args=["company"])
        body = {"slug": "x2", "name": "x", "issuer": ISSUER, "client_id": "c"}
        for response in (
            api_client.post(reverse(API_LIST), body, format="json"),
            api_client.patch(detail, {"name": "x"}, format="json"),
            api_client.delete(detail),
        ):
            assert response.status_code == 403
            assert response.json()["code"] == "reauthentication_required"
        provider.refresh_from_db()
        assert provider.name == "Company SSO"

    def test_a_member_and_a_token_get_nothing(
        self, client: Client, api_client: APIClient, alice: User, admin_user: User
    ) -> None:
        declare(admin_user)
        detail = reverse("api-v1:instance-provider-detail", args=["company"])
        recent(client, alice)
        assert client.get(reverse(API_LIST)).status_code == 403
        assert client.get(detail).status_code == 403
        home = home_services.create_home(admin_user, name="Own")
        _token, raw = token_services.issue_token(
            admin_user, name="all", scopes=["read", "write"], homes=[home]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        for response in (
            api_client.get(reverse(API_LIST)),
            api_client.get(detail),
            api_client.patch(detail, {"name": "x"}, format="json"),
            api_client.delete(detail),
            api_client.post(reverse(API_CHECK), {"issuer": ISSUER}, format="json"),
        ):
            assert response.status_code == 403
        assert OidcProvider.objects.get().name == "Company SSO"

    def test_the_check_endpoint(self, admin_api: APIClient, monkeypatch: Any) -> None:
        monkeypatch.setattr(providers, "discover", lambda issuer: "ok")
        response = admin_api.post(reverse(API_CHECK), {"issuer": ISSUER}, format="json")
        assert response.json() == {"ok": True, "detail": str(providers.CHECK_MESSAGES["ok"])}
        for _ in range(6):
            response = admin_api.post(reverse(API_CHECK), {"issuer": ISSUER}, format="json")
        assert response.status_code == 429

    def test_the_schema_describes_the_endpoints(self, admin_api: APIClient) -> None:
        schema = admin_api.get(reverse("api-schema"), HTTP_ACCEPT="application/json").json()
        assert "/api/v1/instance/providers/" in schema["paths"]
        assert "/api/v1/instance/providers/{slug}/" in schema["paths"]
        assert "/api/v1/instance/provider-check/" in schema["paths"]


class TestContentSecurityPolicy:
    def _form_action(self, client: Client) -> str:
        policy = client.get(reverse("account_login"))["Content-Security-Policy"]
        return next(p for p in policy.split(";") if p.strip().startswith("form-action"))

    def test_form_action_follows_the_enabled_issuers_only(
        self, client: Client, admin_user: User
    ) -> None:
        assert self._form_action(client).split() == ["form-action", "'self'"]
        provider = declare(admin_user)
        declare(admin_user, slug="off", issuer="https://off.example.com", enabled=False)
        # The sources of the directive, one by one: exactly 'self' and the enabled origin.
        assert self._form_action(client).split() == [
            "form-action",
            "'self'",
            "https://id.example.com",
        ]
        providers.update(admin_user, provider, {"enabled": False})
        assert self._form_action(client).split() == ["form-action", "'self'"]


class TestSecretsStayInside:
    def test_no_surface_carries_the_secret(
        self,
        admin_client: Client,
        admin_api: APIClient,
        admin_user: User,
        caplog: Any,
        monkeypatch: Any,
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            form(admin_client, reverse(LIST), slug="company", secret=SECRET)
            url = reverse("instance:provider", kwargs={"slug": "company"})
            refused = form(admin_client, url, secret=SECRET, issuer="http://bad.example")
            assert refused.status_code == 422
            admin_api.patch(
                reverse("api-v1:instance-provider-detail", args=["company"]),
                {"secret": SECRET + "-api"},
                format="json",
            )
            monkeypatch.setattr(providers, "_resolve", lambda host, port: ["192.0.2.10"])
            monkeypatch.setattr(
                providers, "_get", lambda *a: (200, json.dumps({"secret": SECRET}).encode())
            )
            outputs = [
                refused.text,
                admin_client.get(reverse(LIST)).text,
                admin_client.get(url).text,
                admin_api.get(reverse(API_LIST)).text,
                admin_api.get(reverse("api-v1:instance-provider-detail", args=["company"])).text,
                admin_client.get(reverse("instance:audit")).text,
                admin_api.get(reverse("api-v1:instance-audit-list")).text,
                admin_api.post(reverse(API_CHECK), {"issuer": ISSUER}, format="json").text,
                form(admin_client, url, test="1").text,
                admin_client.get(reverse("account_login")).text,
            ]
        outputs.append(
            json.dumps(list(AuditEvent.objects.values_list("action", "detail")), default=str)
        )
        outputs.append(caplog.text)
        for output in outputs:
            assert SECRET not in output
        assert not OidcProvider.objects.filter(secret__contains=SECRET).exists()
        assert get_adapter().get_app(None, "company").secret == SECRET + "-api"
        actions = list(AuditEvent.objects.values_list("action", flat=True))
        assert actions.count("provider.secret_changed") == 2
        # Pointed at another issuer, then enabled again: nothing is left for that issuer.
        assert form(admin_client, url, issuer=EVIL, enabled=False).status_code == 302
        providers.update(admin_user, OidcProvider.objects.get(), {"enabled": True})
        assert get_adapter().get_app(None, "company").secret == ""
        assert not OidcProvider.all_objects.exclude(secret="").exists()
        for output in (
            admin_client.get(reverse("instance:audit")).text,
            admin_api.get(reverse("api-v1:instance-provider-detail", args=["company"])).text,
        ):
            assert SECRET not in output

    def test_an_unreadable_secret_is_said_not_fatal(
        self, admin_client: Client, admin_user: User
    ) -> None:
        declare(admin_user)
        OidcProvider.objects.update(secret="v1:garbage")
        page = admin_client.get(reverse("instance:provider", kwargs={"slug": "company"})).text
        assert "can no longer be read" in page
        assert get_adapter().get_app(None, "company").secret == ""

    def test_changes_are_audited_with_old_and_new_values(self, admin_user: User) -> None:
        provider = declare(admin_user)
        providers.update(admin_user, provider, {"name": "New", "pkce": False})
        rows = AuditEvent.objects.filter(action="provider.changed").order_by("created_at")
        assert [(r.detail["setting"], r.detail["old"], r.detail["new"]) for r in rows] == [
            ("name", "Company SSO", "New"),
            ("pkce", "true", "false"),
        ]


class TestDiscovery:
    """The test button reads the issuer's configuration, and nothing else, safely."""

    GOOD = {
        "issuer": ISSUER,
        "authorization_endpoint": ISSUER + "/auth",
        "token_endpoint": ISSUER + "/token",
        "jwks_uri": ISSUER + "/certs",
    }

    def _serve(
        self, monkeypatch: Any, status: int, body: Any, address: str = "192.0.2.10"
    ) -> list[Any]:
        calls: list[Any] = []
        monkeypatch.setattr(providers, "_resolve", lambda host, port: [address])

        def get(*args: Any) -> tuple[int, bytes]:
            calls.append(args)
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            return status, raw

        monkeypatch.setattr(providers, "_get", get)
        return calls

    def test_a_valid_configuration(self, monkeypatch: Any) -> None:
        calls = self._serve(monkeypatch, 200, self.GOOD)
        assert providers.discover(ISSUER + "/") == "ok"
        assert calls == [
            (
                "192.0.2.10",
                443,
                "id.example.com",
                "/realms/company/.well-known/openid-configuration",
            )
        ]

    @pytest.mark.parametrize(
        ("status", "body", "code"),
        [
            (404, b"", "not_found"),
            (302, b"", "not_found"),  # a redirect is not followed
            (200, b"<html>", "not_oidc"),
            (200, [], "not_oidc"),
            (200, b"x" * (providers.DISCOVERY_MAX_BYTES + 1), "not_oidc"),
            (200, {**GOOD, "jwks_uri": "http://id.example.com/certs"}, "not_oidc"),
            (200, {**GOOD, "issuer": "https://other.example.com"}, "mismatch"),
        ],
    )
    def test_what_is_not_a_configuration(
        self, monkeypatch: Any, status: int, body: Any, code: str
    ) -> None:
        self._serve(monkeypatch, status, body)
        assert providers.discover(ISSUER) == code

    @pytest.mark.parametrize(
        "address",
        ["127.0.0.1", "::1", "169.254.169.254", "::ffff:127.0.0.1", "0.0.0.0", "224.0.0.1"],  # noqa: S104,
    )
    def test_the_instance_itself_and_link_local_services_are_not_called(
        self, monkeypatch: Any, address: str
    ) -> None:
        calls = self._serve(monkeypatch, 200, self.GOOD, address=address)
        assert providers.discover(ISSUER) == "blocked"
        assert calls == []

    @pytest.mark.parametrize(
        ("address", "code"),
        [
            # NAT64 (RFC 6052): the IPv4 address is the last 32 bits.
            ("64:ff9b::7f00:1", "blocked"),  # 127.0.0.1
            ("64:ff9b::a9fe:a9fe", "blocked"),  # 169.254.169.254
            ("64:ff9b::c000:20a", "ok"),  # 192.0.2.10, reached through the gateway
            # 6to4 (RFC 3056): the IPv4 address follows 2002::/16.
            ("2002:7f00:1::1", "blocked"),
            ("2002:a9fe:a9fe::1", "blocked"),
            ("2002:c000:20a::1", "ok"),
            # Teredo (RFC 4380): the client address, inverted, in the last 32 bits.
            ("2001:0:c000:20a::80ff:fffe", "blocked"),  # client 127.0.0.1
        ],
    )
    def test_an_ipv6_address_is_judged_by_the_ipv4_one_it_carries(
        self, monkeypatch: Any, address: str, code: str
    ) -> None:
        calls = self._serve(monkeypatch, 200, self.GOOD, address=address)
        assert providers.discover(ISSUER) == code
        assert len(calls) == (code == "ok")
        assert providers._forbidden_address(ipaddress.ip_address(address)) is (code != "ok")

    def test_a_private_network_is_called(self, monkeypatch: Any) -> None:
        calls = self._serve(monkeypatch, 200, self.GOOD, address="198.18.0.7")
        assert providers.discover(ISSUER) == "ok"
        assert calls[0][0] == "198.18.0.7"

    def test_an_invalid_issuer_is_not_called(self, monkeypatch: Any) -> None:
        calls = self._serve(monkeypatch, 200, self.GOOD)
        assert providers.discover("http://id.example.com") == "invalid"
        assert providers.discover("https://127.0.0.1") == "invalid"
        assert calls == []

    def test_network_failures_say_one_word(self, monkeypatch: Any) -> None:
        import ssl

        def unresolvable(host: str, port: int) -> list[str]:
            raise OSError("no such host")

        monkeypatch.setattr(providers, "_resolve", unresolvable)
        assert providers.discover(ISSUER) == "unreachable"
        monkeypatch.setattr(providers, "_resolve", lambda host, port: ["192.0.2.10"])
        for error, code in ((ssl.SSLError("bad cert"), "tls"), (OSError("refused"), "unreachable")):

            def fail(*args: Any, error: Exception = error) -> tuple[int, bytes]:
                raise error

            monkeypatch.setattr(providers, "_get", fail)
            assert providers.discover(ISSUER) == code

    def test_the_connection_goes_to_the_checked_address(self, monkeypatch: Any) -> None:
        opened: list[Any] = []

        class FakeSocket:
            def close(self) -> None:
                pass

        def create_connection(address: Any, timeout: Any) -> FakeSocket:
            opened.append(address)
            raise OSError("stop here")

        monkeypatch.setattr(providers.socket, "create_connection", create_connection)
        with pytest.raises(OSError, match="stop here"):
            providers._get("192.0.2.10", 8443, "id.example.com", "/x")
        assert opened == [("192.0.2.10", 8443)]

    def test_only_administrators_test(self, alice: User) -> None:
        with pytest.raises(PermissionDenied):
            providers.check(alice, ISSUER)


@pytest.mark.django_db(transaction=True)
def test_the_migration_can_be_undone_and_redone() -> None:
    from django.db import connection

    call_command("migrate", "instance", "0002", verbosity=0)
    assert "instance_oidcprovider" not in connection.introspection.table_names()
    call_command("migrate", "instance", verbosity=0)
    assert "instance_oidcprovider" in connection.introspection.table_names()
