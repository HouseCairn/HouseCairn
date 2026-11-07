import pytest
from django.test import Client, override_settings
from django.urls import reverse

from housecairn.accounts.models import User

pytestmark = pytest.mark.django_db


class TestUserModel:
    def test_email_is_the_identifier(self) -> None:
        user = User.objects.create_user(email="Someone@EXAMPLE.com", password="x" * 12)
        assert user.email == "Someone@example.com"
        assert user.check_password("x" * 12)
        assert not user.is_staff
        assert User.USERNAME_FIELD == "email"

    def test_email_is_required(self) -> None:
        with pytest.raises(ValueError, match="email"):
            User.objects.create_user(email="", password="x")

    def test_without_password(self) -> None:
        user = User.objects.create_user(email="sso@example.com")
        assert not user.has_usable_password()

    def test_superuser(self) -> None:
        admin = User.objects.create_superuser(email="admin@example.com", password="x" * 12)
        assert admin.is_staff
        assert admin.is_superuser
        with pytest.raises(ValueError, match="superuser"):
            User.objects.create_superuser(email="b@example.com", password="x", is_staff=False)


class TestSignIn:
    def test_login_page_uses_the_application_layout(self, client: Client) -> None:
        response = client.get(reverse("account_login"))
        assert response.status_code == 200
        assert "css/tokens.css" in response.text
        assert 'class="content auth-panel"' in response.text
        assert 'id="passkey_login"' in response.text

    def test_sign_in_with_email(self, client: Client, alice: User) -> None:
        from tests.conftest import PASSWORD

        response = client.post(
            reverse("account_login"), {"login": alice.email, "password": PASSWORD}
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("homes:list")

    def test_signup_is_closed_by_default(self, client: Client) -> None:
        response = client.get(reverse("account_signup"))
        assert "closed" in response.text.lower()

    @override_settings(HOUSECAIRN_SIGNUP_OPEN=True)
    def test_signup_can_be_opened(self, client: Client) -> None:
        response = client.get(reverse("account_signup"))
        assert 'name="email"' in response.text

    def test_mfa_types(self) -> None:
        from django.conf import settings

        assert set(settings.MFA_SUPPORTED_TYPES) == {"totp", "recovery_codes", "webauthn"}

    def test_social_signup_follows_setting(self) -> None:
        from housecairn.accounts.adapters import SocialAccountAdapter

        adapter = SocialAccountAdapter()
        with override_settings(HOUSECAIRN_OIDC_SIGNUP_OPEN=False):
            assert adapter.is_open_for_signup(None, None) is False  # type: ignore[arg-type]
        with override_settings(HOUSECAIRN_OIDC_SIGNUP_OPEN=True):
            assert adapter.is_open_for_signup(None, None) is True  # type: ignore[arg-type]


class TestAdmin:
    @pytest.mark.parametrize(
        "url",
        [
            "admin:accounts_user_changelist",
            "admin:accounts_user_add",
            "admin:homes_home_changelist",
            "admin:homes_home_add",
            "admin:apitokens_apitoken_changelist",
        ],
    )
    def test_pages_load(self, client: Client, url: str) -> None:
        admin = User.objects.create_superuser(email="admin@example.com", password="x" * 12)
        client.force_login(admin)
        assert client.get(reverse(url)).status_code == 200

    def test_tokens_cannot_be_added_and_can_be_revoked(self, client: Client) -> None:
        from housecairn.apitokens import services
        from housecairn.apitokens.models import ApiToken
        from housecairn.homes import services as home_services

        admin = User.objects.create_superuser(email="admin@example.com", password="x" * 12)
        home = home_services.create_home(admin, name="H")
        token, _raw = services.issue_token(admin, name="t", scopes=["read"], homes=[home])
        client.force_login(admin)
        assert client.get(reverse("admin:apitokens_apitoken_add")).status_code == 403
        detail = client.get(reverse("admin:apitokens_apitoken_change", args=[token.id]))
        assert token.digest not in detail.text
        client.post(
            reverse("admin:apitokens_apitoken_changelist"),
            {"action": "revoke", "_selected_action": [str(token.id)]},
        )
        assert ApiToken.objects.get().revoked_at is not None
