"""System checks of HouseCairn's own settings (docs/adr/0012)."""

import pytest
from django.core.checks import run_checks
from django.test import override_settings


def ids(deploy: bool = True) -> list[str]:
    return [m.id for m in run_checks(include_deployment_checks=deploy) if m.id]


class TestSiteUrl:
    def test_email_without_a_public_address_is_flagged(self) -> None:
        with override_settings(EMAIL_HOST="smtp.example.com", HOUSECAIRN_SITE_URL=""):
            assert "housecairn.W001" in ids()

    def test_the_public_address_clears_it(self) -> None:
        with override_settings(
            EMAIL_HOST="smtp.example.com", HOUSECAIRN_SITE_URL="https://home.example.com"
        ):
            assert "housecairn.W001" not in ids()

    def test_without_email_nothing_is_built_from_the_host(self) -> None:
        with override_settings(EMAIL_HOST="", HOUSECAIRN_SITE_URL=""):
            assert "housecairn.W001" not in ids()

    def test_only_a_deployment_check(self) -> None:
        with override_settings(EMAIL_HOST="smtp.example.com", HOUSECAIRN_SITE_URL=""):
            assert "housecairn.W001" not in ids(deploy=False)


class TestOpenSignUp:
    @pytest.mark.parametrize("deploy", [True, False])
    def test_open_sign_up_without_email_is_an_error(self, deploy: bool) -> None:
        with override_settings(HOUSECAIRN_SIGNUP_OPEN=True, EMAIL_HOST=""):
            assert "housecairn.E001" in ids(deploy)

    def test_open_sign_up_with_email_is_fine(self) -> None:
        with override_settings(
            HOUSECAIRN_SIGNUP_OPEN=True,
            EMAIL_HOST="smtp.example.com",
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        ):
            assert "housecairn.E001" not in ids()

    def test_closed_sign_up_needs_nothing(self) -> None:
        with override_settings(HOUSECAIRN_SIGNUP_OPEN=False, EMAIL_HOST=""):
            assert "housecairn.E001" not in ids()
