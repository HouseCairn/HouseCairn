"""The first administrator on a web screen, with a one-time code of the process log.

docs/adr/0056. Each test names, in its docstring, what an implementation without the
rule would do wrong; the rule is what makes it fail.
"""

import io
import logging
import threading
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection, connections
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from housecairn.accounts import services, setup
from housecairn.accounts.models import InstanceSetup, SetupCode, SetupMethod, User
from housecairn.audit.models import AuditEvent

pytestmark = pytest.mark.django_db

PASSWORD = "Tr0ub4dor-and-three-more-words"


@pytest.fixture(autouse=True)
def _fresh_counters() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


def form(code: str, **over: str) -> dict[str, str]:
    data = {
        "code": code,
        "name": "Sam",
        "email": "sam@example.com",
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    data.update(over)
    return data


def issue() -> str:
    code = setup.issue_code()
    assert code is not None
    return code


def submit(client: Client, code: str, **over: str) -> Any:
    return client.post(reverse("setup"), form(code, **over))


def admins() -> int:
    return User.objects.filter(is_staff=True, is_superuser=True).count()


class TestTheCode:
    def test_it_is_random_long_and_stored_as_a_digest(self) -> None:
        """Short, guessable or clear-text codes would pass a test of the screen alone."""
        first, second = issue(), issue()
        assert first != second
        assert len(setup.normalize(first)) * 5 >= 128
        stored = SetupCode.objects.get()
        assert stored.digest == setup.digest_of(second)
        assert setup.normalize(second) not in stored.digest
        assert second not in str(stored.__dict__)

    def test_it_is_written_in_groups_that_can_be_typed_back(self) -> None:
        code = issue()
        assert all(len(group) == 4 for group in code.split("-"))
        client = Client()
        loose = " " + code.lower().replace("-", " ") + " "
        assert submit(client, loose).status_code == 302

    def test_it_expires_after_an_hour(self) -> None:
        """A code that never expires would stay valid in every archived log."""
        issue()
        lifetime = SetupCode.objects.get().expires_at - SetupCode.objects.get().created_at
        assert timedelta(minutes=59) < lifetime <= timedelta(hours=1)

    def test_a_new_code_replaces_the_unused_ones(self) -> None:
        """Codes piling up at each restart would multiply the codes that open the screen."""
        old = issue()
        new = issue()
        assert SetupCode.objects.count() == 1
        client = Client()
        assert submit(client, old).status_code == 400
        assert submit(client, new).status_code == 302

    def test_none_is_issued_once_an_administrator_exists(self, make_user: Any) -> None:
        """The start-up code must not appear on an instance that already has its administrator."""
        make_user("boss@example.com", is_staff=True, is_superuser=True)
        assert setup.issue_code() is None
        assert SetupCode.objects.count() == 0
        err = io.StringIO()
        call_command("setup_code", stderr=err)
        assert err.getvalue() == ""

    def test_the_unused_ones_are_forgotten_once_an_administrator_exists(
        self, make_user: Any
    ) -> None:
        issue()
        make_user("boss@example.com", is_staff=True, is_superuser=True)
        assert setup.issue_code() is None
        assert SetupCode.objects.filter(used_at__isnull=True).count() == 0

    @override_settings(HOUSECAIRN_SETUP_SCREEN=False)
    def test_none_is_issued_when_the_screen_is_off(self) -> None:
        assert setup.issue_code() is None
        assert SetupCode.objects.count() == 0

    def test_the_command_writes_the_code_and_the_address_in_the_log(self) -> None:
        err = io.StringIO()
        call_command("setup_code", stderr=err)
        text = err.getvalue()
        assert reverse("setup") in text
        code = SetupCode.objects.get()
        written = [line.split(": ", 1)[1] for line in text.splitlines() if "code:" in line]
        assert setup.digest_of(written[0]) == code.digest

    @override_settings(HOUSECAIRN_SITE_URL="https://home.example.com/")
    def test_the_address_is_the_public_one_when_it_is_set(self) -> None:
        err = io.StringIO()
        call_command("setup_code", stderr=err)
        assert "https://home.example.com/setup/" in err.getvalue()


class TestTheScreen:
    def test_it_creates_the_administrator_and_signs_them_in(self) -> None:
        """No account, a plain account, or no sign-in would each be visible here."""
        client = Client()
        code = issue()
        assert client.get(reverse("setup")).status_code == 200
        response = submit(client, code)
        assert response.status_code == 302
        assert response["Location"] == reverse("instance:overview")
        user = User.objects.get(email="sam@example.com")
        assert user.is_staff
        assert user.is_superuser
        assert user.is_active
        assert user.display_name == "Sam"
        assert user.check_password(PASSWORD)
        assert client.session["_auth_user_id"] == str(user.pk)
        address = EmailAddress.objects.get(user=user)
        assert address.verified
        assert address.primary
        assert client.get(response["Location"]).status_code == 200

    def test_the_setup_row_and_the_audit_log_record_it(self) -> None:
        code = issue()
        submit(Client(), code)
        user = User.objects.get()
        setup_row = InstanceSetup.objects.get()
        assert setup_row.method == SetupMethod.SETUP_SCREEN
        assert setup_row.first_user == user
        event = AuditEvent.objects.get(action="instance.first_admin_created")
        assert event.actor == user
        assert event.detail == {"by": "setup_screen"}
        assert setup.normalize(code) not in str(event.detail)

    def test_a_code_works_once(self) -> None:
        """Without `used_at`, the code of a deleted administrator would create another one."""
        client = Client()
        code = issue()
        assert submit(client, code).status_code == 302
        User.objects.all().delete()
        # The screen is open again (no administrator), the code is not.
        again = submit(Client(), code, email="other@example.com")
        assert again.status_code == 400
        assert not User.objects.exists()

    def test_a_wrong_code_is_refused(self) -> None:
        issue()
        response = submit(Client(), "AAAA-BBBB-CCCC-DDDD-EEEE-FFFF-GGGG-HHHH")
        assert response.status_code == 400
        assert not User.objects.exists()

    def test_an_expired_code_is_refused(self) -> None:
        """Without the expiry test, a code from last month's log still opens the screen."""
        code = issue()
        SetupCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        assert submit(Client(), code).status_code == 400
        assert not User.objects.exists()

    def test_wrong_expired_and_used_codes_get_the_same_answer(self) -> None:
        """The page must not tell a guesser that a code was once good."""
        client = Client()
        wrong = submit(client, "AAAA-BBBB-CCCC-DDDD-EEEE-FFFF-GGGG-HHHH").content.decode()
        code = issue()
        SetupCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        expired = submit(client, code).content.decode()
        fresh = issue()
        submit(client, fresh)
        User.objects.all().delete()
        used = submit(client, fresh).content.decode()

        def error(page: str) -> str:
            start = page.index("This code is not valid")
            return page[start : page.index("</", start)]

        assert error(wrong) == error(expired) == error(used)

    def test_a_refused_form_gives_the_code_back_to_nobody(self) -> None:
        """The field is never refilled: a typed secret would sit in the page and its history."""
        code = issue()
        page = submit(Client(), "ZZZZ-NOT-THE-CODE").content.decode()
        assert "ZZZZ-NOT-THE-CODE" not in page
        page = submit(Client(), code, password2="different").content.decode()
        assert setup.normalize(code) not in setup.normalize(page)
        assert code not in page

    def test_a_form_refused_for_another_reason_keeps_the_code_usable(self) -> None:
        """If the claim were not rolled back, a typo in the address would burn the code."""
        code = issue()
        client = Client()
        User.objects.create_user(email="sam@example.com", password=PASSWORD)
        taken = submit(client, code)
        assert taken.status_code == 400
        assert SetupCode.objects.get().used_at is None
        assert admins() == 0
        assert submit(client, code, email="sam.admin@example.com").status_code == 302

    def test_the_password_rules_of_django_apply(self) -> None:
        code = issue()
        client = Client()
        assert submit(client, code, password1="password", password2="password").status_code == 400
        assert submit(client, code, password2="different").status_code == 400
        assert submit(client, code, password1="sam", password2="sam").status_code == 400
        assert not User.objects.exists()
        assert SetupCode.objects.get().used_at is None

    def test_a_name_is_required(self) -> None:
        code = issue()
        assert submit(Client(), code, name="  ").status_code == 400
        assert not User.objects.exists()

    def test_a_forged_post_is_refused(self) -> None:
        """CSRF: the screen creates an administrator, so a cross-site post must fail."""
        code = issue()
        client = Client(enforce_csrf_checks=True)
        assert submit(client, code).status_code == 403
        assert not User.objects.exists()
        page = client.get(reverse("setup"))
        assert "csrfmiddlewaretoken" in page.content.decode()

    def test_it_is_not_cached(self) -> None:
        assert "no-store" in Client().get(reverse("setup"))["Cache-Control"]


class TestWhenThereIsAnAdministrator:
    def test_the_screen_is_a_404(self, make_user: Any) -> None:
        """Otherwise a leaked code would add an administrator to a running instance."""
        code = issue()
        make_user("boss@example.com", is_staff=True, is_superuser=True)
        client = Client()
        assert client.get(reverse("setup")).status_code == 404
        assert submit(client, code).status_code == 404
        assert not User.objects.filter(email="sam@example.com").exists()

    def test_an_inactive_administrator_does_not_count(self, make_user: Any) -> None:
        make_user("old@example.com", is_staff=True, is_superuser=True, is_active=False)
        assert setup.is_available()

    def test_a_plain_account_does_not_close_it(self, make_user: Any) -> None:
        """Open sign-up can leave accounts and no administrator: the screen is the way out."""
        make_user("plain@example.com")
        code = issue()
        assert submit(Client(), code).status_code == 302
        assert admins() == 1

    @override_settings(HOUSECAIRN_SETUP_SCREEN=False)
    def test_the_variable_switches_the_screen_off(self) -> None:
        client = Client()
        assert client.get(reverse("setup")).status_code == 404
        assert submit(client, "ANY").status_code == 404
        assert b"setup" not in client.get(reverse("account_login")).content

    def test_the_variable_is_read_from_the_environment(self, monkeypatch: Any) -> None:
        from environ import Env

        monkeypatch.setenv("HOUSECAIRN_SETUP_SCREEN", "false")
        assert Env().bool("HOUSECAIRN_SETUP_SCREEN", default=True) is False
        monkeypatch.delenv("HOUSECAIRN_SETUP_SCREEN")
        assert Env().bool("HOUSECAIRN_SETUP_SCREEN", default=True) is True


class TestSignIn:
    def test_the_sign_in_page_points_to_the_screen_when_nobody_has_an_account(self) -> None:
        """Without it, a fresh instance shows a sign-in form nobody can use, and says nothing."""
        response = Client().get(reverse("account_login"))
        assert response.status_code == 200
        page = response.content.decode()
        assert f'href="{reverse("setup")}"' in page
        assert "no administrator yet" in page

    def test_the_sign_in_page_points_to_the_screen_with_plain_accounts_too(
        self, make_user: Any
    ) -> None:
        make_user("plain@example.com")
        response = Client().get(reverse("account_login"))
        assert response.status_code == 200
        assert reverse("setup") in response.content.decode()

    def test_the_sign_in_page_does_not_mention_it_with_an_administrator(
        self, make_user: Any
    ) -> None:
        make_user("boss@example.com", is_staff=True, is_superuser=True)
        response = Client().get(reverse("account_login"))
        assert response.status_code == 200
        assert reverse("setup") not in response.content.decode()


class TestNothingOfTheCodeLeaks:
    def test_it_is_in_no_response_no_audit_entry_and_no_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The code lives in the process log and the database digest, nowhere else."""
        caplog.set_level(logging.DEBUG)
        code = issue()
        needle = setup.normalize(code)
        client = Client()
        seen: list[str] = []

        def look(response: Any) -> None:
            seen.append(response.content.decode())
            seen.extend(f"{key}: {value}" for key, value in response.items())
            seen.extend(str(c.value) for c in response.cookies.values())

        look(client.get(reverse("setup")))
        look(submit(client, code, password2="x"))
        done = submit(client, code)
        look(done)
        look(client.get(done["Location"]))
        look(client.get(reverse("instance:audit")))
        for page in seen:
            assert needle not in setup.normalize(page)
            assert setup.digest_of(code) not in page
        assert needle not in setup.normalize(str(list(AuditEvent.objects.values())))
        assert needle not in setup.normalize(caplog.text)
        assert needle not in setup.normalize(str(dict(client.session)))


class TestTheLimit:
    def test_the_tries_of_one_address_are_limited(self) -> None:
        """Without the limit a guesser may try as fast as the server answers."""
        client = Client()
        codes = [submit(client, "AAAA-BBBB").status_code for _ in range(12)]
        assert codes[:10] == [400] * 10
        assert 429 in codes[10:]
        assert client.get(reverse("setup")).status_code == 429


class TestRaces:
    def test_a_code_claimed_between_the_reading_and_the_claim_creates_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The loser of two simultaneous sends has read the code as good, then finds it used.

        A claim that saves the row blindly (instead of updating it only if it is still
        unused) lets both through: two administrators.
        """
        code = issue()
        real = setup._find_usable

        def another_request_won(given: str) -> SetupCode | None:
            found = real(given)
            SetupCode.objects.filter(pk=found.pk).update(used_at=timezone.now())  # type: ignore[union-attr]
            return found

        monkeypatch.setattr(setup, "_find_usable", another_request_won)
        with pytest.raises(setup.SetupCodeInvalidError):
            setup.create_first_admin(
                code=code, email="late@example.com", name="Late", password=PASSWORD
            )
        assert not User.objects.exists()

    @pytest.mark.django_db(transaction=True)
    def test_two_simultaneous_sends_create_one_administrator(self) -> None:
        """On PostgreSQL, two connections: the second waits for the row, then is refused."""
        if connection.vendor != "postgresql":
            pytest.skip("two writers at once need PostgreSQL; SQLite runs one write at a time")
        code = issue()
        barrier = threading.Barrier(2)
        statuses: list[int] = []

        def send(address: str) -> None:
            client = Client()
            try:
                barrier.wait(timeout=10)
                statuses.append(submit(client, code, email=address).status_code)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=send, args=(f"admin{n}@example.com",)) for n in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert sorted(statuses) in ([302, 400], [302, 404])
        assert admins() == 1
        assert User.objects.count() == 1


class TestTheOtherWaysIn:
    def test_oidc_bootstrap_closes_the_screen(self) -> None:
        """Whichever creates the first administrator first closes the other."""
        code = issue()
        user = User(email="oidc@example.com")

        def save() -> User:
            user.set_unusable_password()
            user.save()
            return user

        services.create_first_admin(user, save)
        assert not setup.is_available()
        client = Client()
        assert client.get(reverse("setup")).status_code == 404
        assert submit(client, code).status_code == 404
        assert admins() == 1

    def test_the_screen_closes_oidc_bootstrap(self) -> None:
        submit(Client(), issue())
        assert services.oidc_signup_decision("oidc@example.com", True) is services.Decision.REFUSED

    def test_createsuperuser_closes_the_screen(self) -> None:
        code = issue()
        call_command("createsuperuser", interactive=False, email="cli@example.com", verbosity=0)
        assert submit(Client(), code).status_code == 404
