"""Sign-up through OIDC: closed by default, first account as administrator.

The identity provider is simulated: each test builds the sign-in allauth would
receive from the provider's userinfo endpoint and runs allauth's own login
flow on it. Nothing goes to the network.
"""

import logging
import os
import pathlib
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from typing import Any
from unittest import mock

import pytest
from allauth.account.middleware import AccountMiddleware
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter, get_adapter
from allauth.socialaccount.internal.flows.login import complete_login
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from housecairn.accounts import services
from housecairn.accounts.adapters import SocialAccountAdapter, provider_identity
from housecairn.accounts.models import InstanceSetup, SetupMethod, User

pytestmark = pytest.mark.django_db

PROVIDER_ID = "test-idp"
OIDC_PROVIDERS = {
    "openid_connect": {
        "APPS": [
            {
                "provider_id": PROVIDER_ID,
                "name": "Test identity provider",
                "client_id": "housecairn",
                "secret": "not-a-secret",
                "settings": {"server_url": "https://id.example.com"},
            }
        ]
    }
}
REFUSED_TEXT = "No account on this instance matches this identity"


@pytest.fixture(autouse=True)
def oidc_provider() -> Iterator[None]:
    with override_settings(SOCIALACCOUNT_PROVIDERS=OIDC_PROVIDERS):
        yield


def run_in_request(
    action: Callable[[HttpRequest], HttpResponse],
) -> tuple[HttpResponse, HttpRequest]:
    """Runs `action` inside the middleware stack, as allauth expects."""
    request = RequestFactory().get(f"/accounts/oidc/{PROVIDER_ID}/login/callback/")
    handler: Any = AccountMiddleware(action)
    for middleware in (MessageMiddleware, AuthenticationMiddleware, SessionMiddleware):
        handler = middleware(handler)
    response: HttpResponse = handler(request)
    return response, request


def sociallogin_for(request: HttpRequest, **claims: Any) -> SocialLogin:
    """The sign-in allauth builds from the provider's userinfo response."""
    claims.setdefault("sub", f"sub-{claims.get('email', 'none')}")
    provider = get_adapter().get_provider(request, PROVIDER_ID)
    sociallogin: SocialLogin = provider.sociallogin_from_response(request, {"userinfo": claims})
    return sociallogin


def sign_in(**claims: Any) -> tuple[HttpResponse, HttpRequest]:
    def action(request: HttpRequest) -> HttpResponse:
        response: HttpResponse = complete_login(request, sociallogin_for(request, **claims))
        return response

    return run_in_request(action)


def admins() -> list[User]:
    return list(User.objects.filter(is_superuser=True))


def assert_refused(response: HttpResponse) -> None:
    assert response.status_code == 403
    assert REFUSED_TEXT in response.content.decode()


class TestBootstrap:
    def test_first_oidc_account_becomes_administrator(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="housecairn.security"):
            response, request = sign_in(email="first@example.com", email_verified=True)
        assert response.status_code == 302
        user = User.objects.get()
        assert user.email == "first@example.com"
        assert user.is_staff
        assert user.is_superuser
        assert request.user == user
        assert SocialAccount.objects.get().user == user
        setup = InstanceSetup.objects.get()
        assert setup.method == SetupMethod.OIDC
        assert setup.first_user == user
        [record] = [r for r in caplog.records if r.name == "housecairn.security"]
        assert record.levelno == logging.WARNING
        assert record.getMessage() == "first account created as instance administrator via OIDC"
        assert "first@example.com" not in record.getMessage()

    def test_second_oidc_account_is_refused(self) -> None:
        sign_in(email="first@example.com", email_verified=True)
        response, _request = sign_in(email="second@example.com", email_verified=True)
        assert_refused(response)
        assert list(User.objects.values_list("email", flat=True)) == ["first@example.com"]

    def test_existing_identity_still_signs_in(self) -> None:
        sign_in(email="first@example.com", email_verified=True)
        response, request = sign_in(email="first@example.com", email_verified=True)
        assert response.status_code == 302
        assert request.user.is_authenticated
        assert User.objects.count() == 1

    def test_no_bootstrap_once_an_account_exists(self, make_user: Callable[..., User]) -> None:
        existing = make_user("local@example.com")
        assert InstanceSetup.objects.get().method == SetupMethod.OTHER
        response, _request = sign_in(email="first@example.com", email_verified=True)
        assert_refused(response)
        # Deleting every account does not reopen the bootstrap.
        existing.delete()
        response, _request = sign_in(email="first@example.com", email_verified=True)
        assert_refused(response)
        assert not User.objects.exists()

    def test_local_account_with_the_same_address_is_not_taken_over(
        self, make_user: Callable[..., User]
    ) -> None:
        local = make_user("someone@example.com")
        response, _request = sign_in(email="someone@example.com", email_verified=True)
        assert_refused(response)
        assert not SocialAccount.objects.exists()
        local.refresh_from_db()
        assert not local.is_superuser


@pytest.mark.parametrize("oidc_signup", ["closed", "open"])
@pytest.mark.parametrize("verified", [True, False])
def test_no_account_is_taken_over_by_a_matching_address(
    make_user: Callable[..., User], oidc_signup: str, verified: bool
) -> None:
    """A provider's claim of an address never signs in to, nor links to, a local account.

    Behaviour, not settings: the sign-in of an identity that asserts the address
    of an existing local account leaves that account unlinked and the visitor
    anonymous (docs/adr/0021).
    """
    local = make_user("someone@example.com")
    with override_settings(HOUSECAIRN_OIDC_SIGNUP=oidc_signup):
        response, request = sign_in(email="someone@example.com", email_verified=verified)
    assert not request.user.is_authenticated
    assert response.status_code in {302, 403}
    assert not SocialAccount.objects.exists()
    assert list(User.objects.values_list("email", flat=True)) == ["someone@example.com"]
    local.refresh_from_db()
    assert not local.is_staff
    assert not local.is_superuser


class TestSimultaneousFirstSignIns:
    """Both sign-ins are checked before either account is saved."""

    def _logins(self) -> list[SocialLogin]:
        logins: list[SocialLogin] = []

        def gate(request: HttpRequest) -> HttpResponse:
            for email in ("a@example.com", "b@example.com"):
                login = sociallogin_for(request, email=email, email_verified=True)
                assert SocialAccountAdapter().is_open_for_signup(request, login) is True
                logins.append(login)
            return HttpResponse()

        run_in_request(gate)
        return logins

    def _save(self, login: SocialLogin) -> HttpResponse:
        def action(request: HttpRequest) -> HttpResponse:
            try:
                SocialAccountAdapter().save_user(request, login)
            except ImmediateHttpResponse as refused:
                response: HttpResponse = refused.response
                return response
            return HttpResponse()

        return run_in_request(action)[0]

    def test_only_one_administrator(self) -> None:
        first, second = self._logins()
        assert self._save(first).status_code == 200
        assert_refused(self._save(second))
        assert [u.email for u in admins()] == ["a@example.com"]
        assert User.objects.count() == 1

    def test_the_database_settles_a_race_the_check_missed(self) -> None:
        """Two transactions that both saw an empty database (PostgreSQL)."""
        first, second = self._logins()
        self._save(first)
        late: User = second.user

        def save() -> User:
            late.save()
            return late

        with (
            mock.patch.object(services, "instance_has_accounts", return_value=False),
            pytest.raises(services.FirstAccountTakenError),
        ):
            services.create_first_admin(late, save)
        assert [u.email for u in admins()] == ["a@example.com"]
        assert User.objects.count() == 1

    @pytest.mark.parametrize(("mode", "created"), [("closed", False), ("open", True)])
    def test_race_lost_while_saving(self, mode: str, created: bool) -> None:
        """The second sign-in still saw an empty instance when its save began."""
        first, second = self._logins()
        self._save(first)
        # Seen empty by the decision, then taken inside the transaction.
        seen = mock.patch.object(services, "instance_has_accounts", side_effect=[False, True, True])
        with override_settings(HOUSECAIRN_OIDC_SIGNUP=mode), seen:
            response = self._save(second)
        assert response.status_code == (200 if created else 403)
        assert User.objects.filter(email="b@example.com").exists() is created
        assert [u.email for u in admins()] == ["a@example.com"]

    @override_settings(HOUSECAIRN_OIDC_SIGNUP="open")
    def test_with_open_signup_the_other_gets_a_regular_account(self) -> None:
        first, second = self._logins()
        self._save(first)
        assert self._save(second).status_code == 200
        regular = User.objects.get(email="b@example.com")
        assert not regular.is_staff
        assert not regular.is_superuser
        assert [u.email for u in admins()] == ["a@example.com"]


class TestPinnedBootstrapAddress:
    @pytest.fixture(autouse=True)
    def pinned(self) -> Iterator[None]:
        with override_settings(HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL="Owner@Example.com"):
            yield

    def test_pinned_verified_address_becomes_administrator(self) -> None:
        response, _request = sign_in(email="owner@example.com", email_verified=True)
        assert response.status_code == 302
        assert [u.email for u in admins()] == ["owner@example.com"]

    def test_pinned_address_cannot_be_changed_on_the_way(self) -> None:
        def save_with_another_address(
            _adapter: object, _request: HttpRequest, login: SocialLogin, form: object = None
        ) -> User:
            user: User = login.user
            user.email = "someone@example.com"
            user.save()
            return user

        replaced = mock.patch.object(
            DefaultSocialAccountAdapter,
            "save_user",
            autospec=True,
            side_effect=save_with_another_address,
        )
        with replaced:
            response, _request = sign_in(email="owner@example.com", email_verified=True)
        assert_refused(response)
        assert not User.objects.exists()
        assert not InstanceSetup.objects.exists()

    @pytest.mark.parametrize(
        "claims",
        [
            {"email": "owner@example.com", "email_verified": False},
            {"email": "owner@example.com"},
            {"email": "owner@example.com", "email_verified": "true"},
            {"email": "owner@example.com", "email_verified": "false"},
            {"email": "someone@example.com", "email_verified": True},
            {"email_verified": True},
        ],
        ids=["unverified", "no-claim", "string-true", "string-false", "other", "no-email"],
    )
    def test_anything_else_is_refused(self, claims: dict[str, Any]) -> None:
        response, _request = sign_in(**claims)
        assert_refused(response)
        assert not User.objects.exists()
        assert not InstanceSetup.objects.exists()

    @override_settings(HOUSECAIRN_OIDC_SIGNUP="open")
    def test_open_signup_does_not_bypass_the_pin(self) -> None:
        response, _request = sign_in(email="someone@example.com", email_verified=True)
        assert_refused(response)
        response, _request = sign_in(email="owner@example.com", email_verified=True)
        assert response.status_code == 302
        assert [u.email for u in admins()] == ["owner@example.com"]


class TestOpenSignup:
    @override_settings(HOUSECAIRN_OIDC_SIGNUP="open")
    def test_new_accounts_have_no_administration_rights(
        self, make_user: Callable[..., User]
    ) -> None:
        make_user("local@example.com")
        response, _request = sign_in(email="new@example.com", email_verified=True)
        assert response.status_code == 302
        user = User.objects.get(email="new@example.com")
        assert not user.is_staff
        assert not user.is_superuser

    def test_closed_is_the_default(self) -> None:
        from django.conf import settings

        assert settings.HOUSECAIRN_OIDC_SIGNUP == "closed"
        assert settings.HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL == ""

    def test_invitation_lets_a_verified_address_sign_up(
        self, make_user: Callable[..., User]
    ) -> None:
        from housecairn.homes import services as home_services

        owner = make_user("local@example.com")
        home = home_services.create_home(owner, name="Main house")
        assert services.has_invitation("new@example.com", True) is False
        home_services.invite(
            owner, home, email="New@Example.com", role="member", delivery=home_services.Delivery()
        )
        assert services.has_invitation("new@example.com", True) is True
        # An address the provider does not assert as verified is not enough.
        assert services.has_invitation("new@example.com", False) is False
        refused, _request = sign_in(email="new@example.com", email_verified=False)
        assert refused.status_code == 403
        response, _request = sign_in(email="new@example.com", email_verified=True)
        assert response.status_code == 302
        assert not User.objects.get(email="new@example.com").is_staff

    @override_settings(HOUSECAIRN_OIDC_SIGNUP="open")
    def test_a_handed_over_invitation_needs_the_provider_to_verify_the_address(
        self, make_user: Callable[..., User]
    ) -> None:
        """A link handed over by hand proves nothing: the provider must (docs/adr/0020)."""
        from housecairn.homes import services as home_services

        owner = make_user("local@example.com")
        home = home_services.create_home(owner, name="Main house")
        links = {}
        for address in ("unverified@example.com", "verified@example.com"):
            _invitation, raw = home_services.invite(
                owner, home, email=address, role="member", delivery=home_services.Delivery()
            )
            assert raw is not None
            links[address] = raw
        sign_in(email="unverified@example.com", email_verified=False)
        unverified = User.objects.get(email="unverified@example.com")
        with pytest.raises(PermissionDenied, match="Verify this address"):
            home_services.accept_invitation(unverified, links["unverified@example.com"])
        assert home_services.role_of(unverified, home) is None
        sign_in(email="verified@example.com", email_verified=True)
        member = User.objects.get(email="verified@example.com")
        home_services.accept_invitation(member, links["verified@example.com"])
        assert home_services.role_of(member, home) == "member"

    @pytest.mark.parametrize("value", ["true", "invite"])
    def test_invalid_mode_is_refused_at_start(self, value: str) -> None:
        env = {**os.environ, "HOUSECAIRN_OIDC_SIGNUP": value, "DJANGO_SETTINGS_MODULE": ""}
        result = subprocess.run(
            [sys.executable, "-c", "import tests.settings"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            cwd=pathlib.Path(__file__).resolve().parents[1],
        )
        assert result.returncode != 0
        assert "HOUSECAIRN_OIDC_SIGNUP is not valid: expected one of closed, open" in result.stderr


class TestProviderIdentity:
    def test_reads_the_id_token_without_userinfo(self) -> None:
        login = SocialLogin(
            account=SocialAccount(
                extra_data={"id_token": {"email": " a@example.com ", "email_verified": True}}
            )
        )
        assert provider_identity(login) == ("a@example.com", True)

    def test_no_provider_is_named_in_the_code(self) -> None:
        from django.conf import settings

        providers = [
            app
            for app in settings.INSTALLED_APPS
            if app.startswith("allauth.socialaccount.providers")
        ]
        assert providers == ["allauth.socialaccount.providers.openid_connect"]
        names = re.compile(r"(keycloak|authentik|authelia|okta|auth0|google|microsoft|entra id)")
        sources = pathlib.Path(__file__).resolve().parents[1] / "src" / "housecairn"
        for path in sources.rglob("*"):
            if path.suffix in {".py", ".html", ".txt"} and "vendor" not in path.parts:
                text = path.read_text(encoding="utf-8").lower()
                assert not names.search(text), path


class TestSignInPage:
    def test_no_signup_link_while_signup_is_closed(self, client: Client) -> None:
        page = client.get(reverse("account_login")).content.decode()
        assert reverse("account_signup") not in page
        assert "Sign in with a passkey" not in page

    @override_settings(HOUSECAIRN_SIGNUP_OPEN=True)
    def test_signup_link_when_open(self, client: Client) -> None:
        page = client.get(reverse("account_login")).content.decode()
        assert reverse("account_signup") in page

    def test_refusal_page_is_translated(self) -> None:
        from django.utils import translation

        with translation.override("fr"):
            response, _request = sign_in(email="x@example.com", email_verified=True)
            sign_in_again, _request = sign_in(email="y@example.com", email_verified=True)
        assert response.status_code == 302
        assert sign_in_again.status_code == 403
        assert "Connexion refusée" in sign_in_again.content.decode()


def test_second_marker_is_ignored(make_user: Callable[..., User]) -> None:
    first = make_user("first@example.com")
    with mock.patch.object(InstanceSetup.objects, "exists", return_value=False):
        services.record_first_account(make_user("second@example.com"))
    assert InstanceSetup.objects.get().first_user == first


def test_instance_setup_admin_is_read_only(client: Client) -> None:
    sign_in(email="first@example.com", email_verified=True)
    admin = User.objects.get()
    client.force_login(admin)
    assert client.get(reverse("admin:accounts_instancesetup_changelist")).status_code == 200
    assert client.get(reverse("admin:accounts_instancesetup_add")).status_code == 403
    setup = InstanceSetup.objects.get()
    detail = client.get(reverse("admin:accounts_instancesetup_change", args=[setup.pk]))
    assert detail.status_code == 200
    assert 'name="method"' not in detail.content.decode()
