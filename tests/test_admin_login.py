"""The administration site signs in through allauth only (docs/adr/0022).

Django's own form at /admin/login/ took the password alone: it skipped the second
factor and the rate limits of allauth's sign-in page.
"""

from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from allauth.mfa.totp.internal.auth import (
    TOTP,
    format_hotp_value,
    generate_totp_secret,
    hotp_value,
    yield_hotp_counters_from_time,
)
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db

ACCOUNT_LOGIN = reverse("account_login")


@pytest.fixture(autouse=True)
def _fresh_rate_limits() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin_user(make_user: Callable[..., User]) -> User:
    return make_user("admin@example.com", is_staff=True, is_superuser=True)


def with_totp(user: User) -> str:
    secret = generate_totp_secret()
    TOTP.activate(user, secret)
    return secret


def current_code(secret: str) -> str:
    counters = list(yield_hotp_counters_from_time())
    counter = counters[len(counters) // 2]
    return format_hotp_value(hotp_value(secret, counter))


def signed_in(client: Client) -> bool:
    return "_auth_user_id" in client.session


def next_of(location: str) -> str:
    return parse_qs(urlsplit(location).query)["next"][0]


class TestAdminSignIn:
    def test_the_password_alone_opens_no_session(self, admin_user: User) -> None:
        with_totp(admin_user)
        client = Client()
        response = client.post(
            "/admin/login/?next=/admin/",
            {"username": admin_user.email, "password": PASSWORD},
        )
        assert response.status_code == 302
        assert response["Location"].startswith(ACCOUNT_LOGIN)
        assert not signed_in(client)
        admin = client.get("/admin/")
        assert admin.status_code == 302
        assert admin["Location"].startswith("/admin/login/")
        instance = client.get("/instance/")
        assert instance.status_code == 302
        assert instance["Location"].startswith(ACCOUNT_LOGIN)
        assert client.get("/api/v1/me/").status_code in (401, 403)

    def test_the_admin_opens_after_allauth_and_the_second_factor(
        self, admin_user: User, settings: Any
    ) -> None:
        # One period of tolerance: a code computed just before the period changes still passes.
        settings.MFA_TOTP_TOLERANCE = 1
        secret = with_totp(admin_user)
        client = Client()
        start = client.get("/admin/")
        login_page = client.get(start["Location"])
        assert login_page.status_code == 302
        assert login_page["Location"].startswith(ACCOUNT_LOGIN)
        next_url = next_of(login_page["Location"])
        password = client.post(
            ACCOUNT_LOGIN,
            {"login": admin_user.email, "password": PASSWORD, "next": next_url},
        )
        assert password["Location"].startswith(reverse("mfa_authenticate"))
        assert not signed_in(client)
        assert client.get("/admin/").status_code == 302
        code = client.post(reverse("mfa_authenticate"), {"code": current_code(secret)})
        assert signed_in(client)
        assert code["Location"] == next_url
        assert client.get(code["Location"], follow=True).status_code == 200
        assert client.get("/admin/").status_code == 200

    def test_wrong_passwords_on_the_admin_path_end_in_429(self, admin_user: User) -> None:
        client = Client()
        codes = []
        for attempt in range(40):
            response = client.post(
                "/admin/login/", {"username": admin_user.email, "password": f"wrong-{attempt}"}
            )
            # The admin's form reads no password: every attempt goes to allauth's page.
            assert response.status_code == 302
            assert response["Location"].startswith(ACCOUNT_LOGIN)
            codes.append(
                client.post(
                    response["Location"],
                    {"login": admin_user.email, "password": f"wrong-{attempt}"},
                ).status_code
            )
        assert codes[-1] == 429
        assert not signed_in(client)

    def test_a_hostile_next_is_refused(self, admin_user: User) -> None:
        client = Client()
        response = client.get("/admin/login/?next=//evil.example")
        assert response.status_code == 302
        assert response["Location"].startswith(ACCOUNT_LOGIN)
        next_url = next_of(response["Location"])
        assert next_url.startswith("/")
        assert not next_url.startswith("//")
        signed = client.post(
            ACCOUNT_LOGIN, {"login": admin_user.email, "password": PASSWORD, "next": next_url}
        )
        assert signed_in(client)
        assert signed["Location"] == next_url
        # Signed in, the administration site sends staff to its index, never to `next`.
        assert client.get(signed["Location"])["Location"] == "/admin/"

    def test_a_signed_in_person_who_is_not_staff_gets_403(
        self, make_user: Callable[..., User]
    ) -> None:
        client = Client()
        client.force_login(make_user("someone@example.com"))
        assert client.get("/admin/login/").status_code == 403
