"""Open sign-up: closed by default, protected when open (docs/adr/0024)."""

import hashlib
import re
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse

from housecairn.accounts import antibot, services
from housecairn.accounts.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "a-long-and-unusual-passphrase"
OPEN = {
    "HOUSECAIRN_SIGNUP_OPEN": True,
    "ACCOUNT_EMAIL_VERIFICATION": "mandatory",
    "HOUSECAIRN_SIGNUP_POW_BITS": 8,
    "EMAIL_HOST": "smtp.example.com",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
}


@pytest.fixture(autouse=True)
def _open_signup() -> Iterator[None]:
    cache.clear()
    with override_settings(**OPEN):
        yield
    cache.clear()


def challenge_of(page: str) -> tuple[str, int]:
    match = re.search(r'data-challenge="([0-9a-f]+)"[^>]*data-bits="(\d+)"', page) or re.search(
        r'data-bits="(\d+)"[^>]*data-challenge="([0-9a-f]+)"', page
    )
    assert match, "no challenge on the page"
    first, second = match.groups()
    return (first, int(second)) if len(first) > 3 else (second, int(first))


def works(challenge: str, n: int, bits: int) -> bool:
    digest = hashlib.sha256(f"{challenge}:{n}".encode()).digest()
    return antibot.leading_zero_bits(digest) >= bits


def sign_up(
    client: Client, email: str = "new@example.com", *, solve: bool = True, **extra: str
) -> Any:
    page = client.get(reverse("account_signup")).text
    challenge, bits = challenge_of(page)
    data = {
        "email": email,
        "password1": PASSWORD,
        "password2": PASSWORD,
        "pow_solution": antibot.solve(challenge, bits) if solve else "",
        **extra,
    }
    return client.post(reverse("account_signup"), data)


class TestClosedByDefault:
    @override_settings(HOUSECAIRN_SIGNUP_OPEN=False)
    def test_the_page_is_closed_and_a_post_creates_nothing(self, client: Client) -> None:
        assert "closed" in client.get(reverse("account_signup")).text.lower()
        response = client.post(
            reverse("account_signup"),
            {"email": "x@example.com", "password1": PASSWORD, "password2": PASSWORD},
        )
        assert not User.objects.filter(email="x@example.com").exists()
        assert response.status_code in {200, 302}

    def test_the_default_setting_is_closed(self) -> None:
        import os
        import subprocess
        import sys

        env = {k: v for k, v in os.environ.items() if k != "HOUSECAIRN_SIGNUP_OPEN"}
        env["DJANGO_SETTINGS_MODULE"] = "tests.settings"
        code = (
            "from django.conf import settings as s;"
            "print(s.HOUSECAIRN_SIGNUP_OPEN, s.ACCOUNT_EMAIL_VERIFICATION)"
        )
        out = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
        )
        assert out.stdout.split() == ["False", "optional"]


class TestProofOfWork:
    def test_the_page_carries_a_challenge_and_the_script(self, client: Client) -> None:
        page = client.get(reverse("account_signup")).text
        challenge, bits = challenge_of(page)
        assert len(challenge) == 32
        assert bits == 8
        assert "js/pow.js" in page
        assert "data-pow-status" in page

    def test_a_solved_challenge_creates_the_account_pending_verification(
        self, client: Client
    ) -> None:
        response = sign_up(client)
        assert response.status_code == 302
        user = User.objects.get(email="new@example.com")
        assert not EmailAddress.objects.get(user=user).verified
        assert [m.to for m in mail.outbox] == [["new@example.com"]]
        # Mandatory verification: the account cannot sign in before the address is verified.
        login = client.post(reverse("account_login"), {"login": user.email, "password": PASSWORD})
        assert login.status_code == 302
        assert reverse("homes:list") not in login["Location"]

    def test_a_robot_that_does_not_solve_it_is_refused(self, client: Client) -> None:
        response = sign_up(client, solve=False)
        assert response.status_code == 200
        assert "not a robot" in response.text
        assert not User.objects.exists()
        assert mail.outbox == []

    def test_a_wrong_solution_is_refused(self, client: Client) -> None:
        challenge, bits = challenge_of(client.get(reverse("account_signup")).text)
        wrong = next(str(n) for n in range(100_000) if not works(challenge, n, bits))
        response = client.post(
            reverse("account_signup"),
            {
                "email": "new@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "pow_solution": wrong,
            },
        )
        assert "not a robot" in response.text
        assert not User.objects.exists()

    @pytest.mark.parametrize("junk", ["abc", "-1", "1e3", "9" * 40, " 12", "١٢٣"])
    def test_a_malformed_solution_is_refused_without_error(self, client: Client, junk: str) -> None:
        client.get(reverse("account_signup"))
        response = client.post(
            reverse("account_signup"),
            {
                "email": "new@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "pow_solution": junk,
            },
        )
        assert response.status_code == 200
        assert not User.objects.exists()

    def test_a_solution_works_once(self, client: Client) -> None:
        page = client.get(reverse("account_signup")).text
        challenge, bits = challenge_of(page)
        solution = antibot.solve(challenge, bits)
        data = {
            "email": "a@example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "pow_solution": solution,
        }
        assert client.post(reverse("account_signup"), data).status_code == 302
        # The same solution again, for another address: the challenge is gone.
        again = client.post(reverse("account_signup"), {**data, "email": "b@example.com"})
        assert again.status_code == 200
        assert "not a robot" in again.text
        assert not User.objects.filter(email="b@example.com").exists()

    def test_a_solution_is_bound_to_the_session_that_was_given_the_challenge(
        self, client: Client
    ) -> None:
        first, bits = challenge_of(client.get(reverse("account_signup")).text)
        other = Client()
        second, _bits = challenge_of(other.get(reverse("account_signup")).text)
        # A number that solves the first visitor's challenge and not the second's.
        stolen = next(
            str(n) for n in range(100_000) if works(first, n, bits) and not works(second, n, bits)
        )
        response = other.post(
            reverse("account_signup"),
            {
                "email": "x@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "pow_solution": stolen,
            },
        )
        assert "not a robot" in response.text
        assert not User.objects.exists()

    def test_a_challenge_expires(self, client: Client) -> None:
        page = client.get(reverse("account_signup")).text
        challenge, bits = challenge_of(page)
        solution = antibot.solve(challenge, bits)
        later = SimpleNamespace(time=lambda: time.time() + 3600)
        with mock.patch.object(antibot, "time", later):
            response = client.post(
                reverse("account_signup"),
                {
                    "email": "new@example.com",
                    "password1": PASSWORD,
                    "password2": PASSWORD,
                    "pow_solution": solution,
                },
            )
        assert "not a robot" in response.text
        assert not User.objects.exists()

    def test_a_failed_form_comes_back_with_a_fresh_challenge(self, client: Client) -> None:
        first = challenge_of(client.get(reverse("account_signup")).text)
        response = client.post(
            reverse("account_signup"),
            {"email": "not-an-address", "password1": PASSWORD, "password2": PASSWORD},
        )
        assert challenge_of(response.text)[0] != first[0]

    def test_the_work_asked_follows_the_setting(self, client: Client) -> None:
        with override_settings(HOUSECAIRN_SIGNUP_POW_BITS=12):
            assert challenge_of(client.get(reverse("account_signup")).text)[1] == 12

    def test_the_check_itself(self) -> None:
        assert antibot.leading_zero_bits(b"\x00\x0f") == 12
        assert antibot.leading_zero_bits(b"\x80") == 0
        assert antibot.leading_zero_bits(b"\x00\x00") == 16


class TestNoEnumeration:
    def test_a_known_address_gets_the_same_answer_as_a_new_one(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        make_user("known@example.com")
        known = sign_up(client, "known@example.com")
        fresh = sign_up(Client(), "nobody@example.com")
        assert known.status_code == fresh.status_code == 302
        assert known["Location"] == fresh["Location"]
        assert User.objects.filter(email="known@example.com").count() == 1
        # Both addresses get a mail; neither answer says which account exists.
        assert sorted(m.to[0] for m in mail.outbox) == ["known@example.com", "nobody@example.com"]

    def test_password_reset_answers_alike(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        make_user("known@example.com")
        url = reverse("account_reset_password")
        known = client.post(url, {"email": "known@example.com"})
        unknown = client.post(url, {"email": "nobody@example.com"})
        assert known.status_code == unknown.status_code == 302
        assert known["Location"] == unknown["Location"]
        assert sorted(m.to[0] for m in mail.outbox) == ["known@example.com", "nobody@example.com"]

    def test_the_login_failure_does_not_say_which_part_is_wrong(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        make_user("known@example.com")
        url = reverse("account_login")
        known = client.post(url, {"login": "known@example.com", "password": "wrong-password-1"})
        unknown = client.post(url, {"login": "nobody@example.com", "password": "wrong-password-1"})

        def errors(text: str) -> list[str]:
            return re.findall(r"<(?:li|div)[^>]*(?:error|alert)[^>]*>(.*?)</", text, re.S)

        assert known.status_code == unknown.status_code == 200
        assert errors(known.text) == errors(unknown.text)


class TestDomains:
    def test_only_the_allowed_domains(self, client: Client) -> None:
        with override_settings(HOUSECAIRN_SIGNUP_ALLOWED_DOMAINS=["example.org"]):
            refused = sign_up(client, "x@example.com")
            assert refused.status_code == 200
            assert "not open to addresses of this domain" in refused.text
            assert not User.objects.exists()
            assert sign_up(client, "x@example.org").status_code == 302
            assert sign_up(Client(), "y@mail.example.org").status_code == 302

    def test_the_blocked_domains_never(self, client: Client) -> None:
        with override_settings(HOUSECAIRN_SIGNUP_BLOCKED_DOMAINS=["spam.example"]):
            assert "not open" in sign_up(client, "x@spam.example").text
            assert "not open" in sign_up(Client(), "x@box.spam.example").text
            assert sign_up(Client(), "x@notspam.example").status_code == 302

    def test_the_rules(self) -> None:
        with override_settings(
            HOUSECAIRN_SIGNUP_ALLOWED_DOMAINS=["a.example", "b.example"],
            HOUSECAIRN_SIGNUP_BLOCKED_DOMAINS=["bad.a.example"],
        ):
            assert services.signup_domain_allowed("x@a.example")
            assert services.signup_domain_allowed("X@B.EXAMPLE")
            assert not services.signup_domain_allowed("x@bad.a.example")
            assert not services.signup_domain_allowed("x@c.example")
            assert not services.signup_domain_allowed("x@xa.example")
            assert not services.signup_domain_allowed(None)
            assert not services.signup_domain_allowed("no-at-sign")
        assert services.signup_domain_allowed("anything@anywhere.example")

    def test_invited_people_are_not_held_to_the_lists(self, make_user: Callable[..., User]) -> None:
        from housecairn.instance import services as instance_services

        admin = make_user("admin@example.com", is_staff=True, is_superuser=True)
        with override_settings(HOUSECAIRN_SIGNUP_ALLOWED_DOMAINS=["example.org"]):
            box: list[str] = []
            instance_services.invite(
                admin, email="x@elsewhere.example", send=lambda i, raw: box.append(raw)
            )
            user = instance_services.create_account(box[0], password=PASSWORD)
        assert user.email == "x@elsewhere.example"


class TestRateLimit:
    """Signing up is limited per client address, which is REMOTE_ADDR (docs/adr/0012)."""

    @staticmethod
    def post(client: Client, **headers: str) -> int:
        response = client.post(
            reverse("account_signup"),
            {"email": "x@example.com", "password1": PASSWORD, "password2": PASSWORD},
            headers=headers,
        )
        return int(response.status_code)

    @override_settings(ACCOUNT_RATE_LIMITS={"signup": "3/m/ip"})
    def test_signing_up_is_limited_per_client(self) -> None:
        client = Client(REMOTE_ADDR="203.0.113.7")
        codes = [self.post(client, **{"X-Forwarded-For": f"198.51.100.{i}"}) for i in range(5)]
        assert 429 not in codes[:3]
        assert codes[3:] == [429, 429]

    @override_settings(ACCOUNT_RATE_LIMITS={"signup": "3/m/ip"})
    def test_a_forged_forwarding_header_does_not_dodge_it_behind_the_proxy(self) -> None:
        client = Client(REMOTE_ADDR="127.0.0.1")
        codes = [
            self.post(client, **{"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.9"})
            for i in range(5)
        ]
        assert 429 not in codes[:3]
        assert codes[3:] == [429, 429]

    def test_the_default_limit_is_set(self) -> None:
        from django.conf import settings

        assert settings.ACCOUNT_RATE_LIMITS["signup"] == "10/m/ip,60/d/ip"


class TestOidcOpenSignUpDomains:
    @pytest.mark.parametrize(
        ("signup", "domains", "email", "expected"),
        [
            ("open", [], "x@anywhere.example", "member"),
            ("open", ["example.org"], "x@example.org", "member"),
            ("open", ["example.org"], "x@example.com", "refused"),
            ("closed", [], "x@anywhere.example", "refused"),
        ],
    )
    def test_decision(
        self,
        make_user: Callable[..., User],
        signup: str,
        domains: list[str],
        email: str,
        expected: str,
    ) -> None:
        make_user("someone@example.com")
        with override_settings(
            HOUSECAIRN_OIDC_SIGNUP=signup, HOUSECAIRN_SIGNUP_ALLOWED_DOMAINS=domains
        ):
            assert services.oidc_signup_decision(email, True).value == expected
