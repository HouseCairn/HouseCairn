"""Instance settings in the interface, paired with environment variables (docs/adr/0031)."""

import json
import logging
import re
import smtplib
import ssl
import time
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from allauth.account.internal.userkit import user_id_to_str
from django.core import mail as django_mail
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import DatabaseError
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.audit.models import AuditEvent
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.instance import config, crypto, mail, registry
from housecairn.instance import settings_services as svc
from housecairn.instance.forms import SettingsSectionForm
from housecairn.instance.management.commands import settings_table
from housecairn.instance.models import SettingValue

pytestmark = pytest.mark.django_db

SECRET = "Sm7p-Passw0rd-N0t-In-Any-Output"
WEB = "instance:settings"
API = "api-v1:instance-settings"


def locked(*keys: str, **django_values: Any) -> Any:
    """Pretend that variables set these settings, with the values read from them."""
    return override_settings(HOUSECAIRN_ENV_LOCKED=frozenset(keys), **django_values)


def recent(client: Client | APIClient, user: User, *, age: float = 0) -> None:
    """Sign in, and record that it happened `age` seconds ago, as allauth's sign-in does."""
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


def post(client: Client, section: str, **data: Any) -> Any:
    """What a browser sends: every field of the section as shown, then the changes."""
    form = SettingsSectionForm(registry.Section(section))
    sent: dict[str, Any] = {"section": section}
    for key, field in form.fields.items():
        initial = field.initial
        if isinstance(initial, bool):
            if initial:
                sent[key] = "on"
        elif initial is not None:
            sent[key] = initial
    for key, value in data.items():
        if value is False:
            sent.pop(key, None)
        else:
            sent[key] = value
    return client.post(reverse(WEB), sent)


class TestResolution:
    """Variable, then database, then default, on every kind of setting."""

    def test_default_when_nothing_is_set(self) -> None:
        assert config.get_setting("signup_open") is False
        assert config.get_setting("invitation_lifetime_days") == 7
        assert config.get_setting("signup_blocked_domains") == []
        assert config.get_setting("email_host_password") == ""
        assert config.source("signup_open") == "default"

    def test_the_database_beats_the_default(self, admin_user: User) -> None:
        svc.update(
            admin_user,
            {
                "email_host": "smtp.example.com",
                "signup_open": True,
                "invitation_lifetime_days": 30,
                "signup_blocked_domains": "Spam.example, @bad.example",
                "email_host_password": SECRET,
            },
        )
        assert config.get_setting("signup_open") is True
        assert config.get_setting("invitation_lifetime_days") == 30
        assert config.get_setting("signup_blocked_domains") == ["spam.example", "bad.example"]
        assert config.get_setting("email_host_password") == SECRET
        assert config.source("signup_open") == "database"

    def test_the_variable_beats_the_database(self, admin_user: User) -> None:
        svc.update(
            admin_user,
            {
                "email_host": "smtp.example.com",
                "signup_open": True,
                "invitation_lifetime_days": 30,
                "signup_blocked_domains": "spam.example",
                "email_host_password": SECRET,
            },
        )
        with locked(
            "signup_open",
            "invitation_lifetime_days",
            "signup_blocked_domains",
            "email_host_password",
            HOUSECAIRN_SIGNUP_OPEN=False,
            HOUSECAIRN_INVITATION_LIFETIME_DAYS=3,
            HOUSECAIRN_SIGNUP_BLOCKED_DOMAINS=["other.example"],
            EMAIL_HOST_PASSWORD="from-the-variable",
        ):
            assert config.get_setting("signup_open") is False
            assert config.get_setting("invitation_lifetime_days") == 3
            assert config.get_setting("signup_blocked_domains") == ["other.example"]
            assert config.get_setting("email_host_password") == "from-the-variable"
            assert config.source("signup_open") == "environment"
            assert config.describe("email_host_password").value is None
        # The database value is kept underneath, for when the variable goes.
        assert config.get_setting("invitation_lifetime_days") == 30

    def test_reset_returns_to_the_default(self, admin_user: User) -> None:
        svc.update(admin_user, {"invitation_lifetime_days": 30})
        assert svc.reset(admin_user, "invitation_lifetime_days") is True
        assert config.get_setting("invitation_lifetime_days") == 7
        assert svc.reset(admin_user, "invitation_lifetime_days") is False
        assert not SettingValue.objects.filter(key="invitation_lifetime_days").exists()

    def test_a_value_equal_to_the_default_is_stored_as_none(self, admin_user: User) -> None:
        svc.update(admin_user, {"invitation_lifetime_days": 30})
        svc.update(admin_user, {"invitation_lifetime_days": 7})
        assert not SettingValue.objects.filter(key="invitation_lifetime_days").exists()
        assert config.source("invitation_lifetime_days") == "default"

    def test_a_change_to_the_same_value_is_not_a_change(self, admin_user: User) -> None:
        assert svc.update(admin_user, {"invitation_lifetime_days": 30}) == [
            "invitation_lifetime_days"
        ]
        assert svc.update(admin_user, {"invitation_lifetime_days": 30}) == []
        assert AuditEvent.objects.filter(action="settings.changed").count() == 1

    def test_another_process_sees_a_change_within_the_snapshot_time(self) -> None:
        assert config.get_setting("invitation_lifetime_days") == 7
        SettingValue.objects.create(
            key="invitation_lifetime_days", value="21"
        )  # as another process
        assert config.get_setting("invitation_lifetime_days") == 7
        config._loaded_at -= config.SNAPSHOT_SECONDS + 1
        assert config.get_setting("invitation_lifetime_days") == 21

    def test_an_unreadable_row_falls_back_to_the_default(self, caplog: Any) -> None:
        SettingValue.objects.create(key="invitation_lifetime_days", value="999")
        SettingValue.objects.create(key="email_port", value="not json")
        with caplog.at_level(logging.WARNING, logger="housecairn.settings"):
            assert config.get_setting("invitation_lifetime_days") == 7
            assert config.get_setting("email_port") == 587
        assert "unreadable" in caplog.text

    def test_a_missing_table_falls_back_to_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(*args: Any, **kwargs: Any) -> Any:
            raise DatabaseError("no such table")

        monkeypatch.setattr(SettingValue.objects, "values_list", broken)
        assert config.get_setting("email_port") == 587

    def test_the_environment_is_read_once_with_empty_meaning_unset(self) -> None:
        env = registry.read_environment(
            {"HOUSECAIRN_SIGNUP_OPEN": "yes", "EMAIL_HOST": "  ", "EMAIL_PORT": "2525"}
        )
        assert env.locked == {"signup_open", "email_port"}
        assert env.values["signup_open"] is True
        assert env.values["email_port"] == 2525
        assert env.values["email_host"] == ""

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("HOUSECAIRN_SIGNUP_POW_BITS", "40"),
            ("HOUSECAIRN_INVITATION_LIFETIME_DAYS", "0"),
            ("HOUSECAIRN_OIDC_SIGNUP", "invite"),
            ("HOUSECAIRN_SITE_URL", "https://home.example.com/path"),
            ("HOUSECAIRN_SIGNUP_OPEN", "maybe"),
            ("EMAIL_PORT", "http"),
            ("HOUSECAIRN_SIGNUP_ALLOWED_DOMAINS", "not a domain"),
        ],
    )
    def test_an_invalid_variable_stops_the_start(self, name: str, value: str) -> None:
        with pytest.raises(ImproperlyConfigured, match=name):
            registry.read_environment({name: value})


class TestFollowers:
    """What Django and allauth read from their own settings follows the database."""

    def test_verification_follows_open_sign_up_and_comes_back(self, admin_user: User) -> None:
        from django.conf import settings

        before = settings.ACCOUNT_EMAIL_VERIFICATION
        svc.update(admin_user, {"email_host": "smtp.example.com", "signup_open": True})
        assert settings.ACCOUNT_EMAIL_VERIFICATION == "mandatory"
        assert settings.ACCOUNT_EMAIL_NOTIFICATIONS is True
        svc.reset(admin_user, "signup_open")
        svc.reset(admin_user, "email_host")
        assert before == settings.ACCOUNT_EMAIL_VERIFICATION
        assert settings.ACCOUNT_EMAIL_NOTIFICATIONS is False

    def test_a_pinned_verification_is_left_alone(self, admin_user: User) -> None:
        from django.conf import settings

        with override_settings(
            HOUSECAIRN_EMAIL_VERIFICATION_PINNED=True, ACCOUNT_EMAIL_VERIFICATION="none"
        ):
            svc.update(admin_user, {"email_host": "smtp.example.com", "signup_open": True})
            assert settings.ACCOUNT_EMAIL_VERIFICATION == "none"

    def test_the_mail_backend_uses_the_settings_in_force(self, admin_user: User) -> None:
        assert mail.EmailBackend().host == ""
        svc.update(
            admin_user,
            {
                "email_host": "smtp.example.com",
                "email_port": 2525,
                "email_use_ssl": True,
                "email_host_user": "robot",
                "email_host_password": SECRET,
                "email_timeout": 5,
            },
        )
        backend = mail.EmailBackend()
        assert (backend.host, backend.port, backend.username) == ("smtp.example.com", 2525, "robot")
        assert backend.password == SECRET
        assert backend.use_ssl is True
        assert backend.use_tls is False  # TLS from the first byte wins, Django refuses both
        assert backend.timeout == 5

    def test_without_a_server_messages_go_to_the_console(self, capsys: Any) -> None:
        backend = mail.EmailBackend()
        message = django_mail.EmailMessage("Hello", "Body", to=["to@example.com"])
        assert backend.send_messages([message]) == 1
        assert "Subject: Hello" in capsys.readouterr().out

    def test_the_sender_is_the_one_in_force(self, admin_user: User, monkeypatch: Any) -> None:
        svc.update(
            admin_user,
            {"email_host": "smtp.example.com", "default_from_email": "Home <home@example.com>"},
        )
        sent: list[django_mail.EmailMessage] = []
        monkeypatch.setattr(
            "django.core.mail.backends.smtp.EmailBackend.send_messages",
            lambda self, messages: sent.extend(messages) or len(messages),
        )
        message = django_mail.EmailMessage("Hi", "Body", to=["to@example.com"])
        mail.EmailBackend().send_messages([message])
        assert sent[0].from_email == "Home <home@example.com>"

    @pytest.mark.parametrize(
        ("error", "code"),
        [
            (smtplib.SMTPAuthenticationError(535, b"no"), "auth"),
            (ssl.SSLError("handshake"), "tls"),
            (smtplib.SMTPNotSupportedError("no starttls"), "tls"),
            (OSError("refused"), "unreachable"),
            (smtplib.SMTPServerDisconnected("gone"), "unreachable"),
        ],
    )
    def test_the_connection_test_names_the_failure_in_a_word(
        self, admin_user: User, monkeypatch: Any, error: Exception, code: str
    ) -> None:
        svc.update(admin_user, {"email_host": "smtp.example.com"})

        def fail(self: Any) -> None:
            raise error

        monkeypatch.setattr("django.core.mail.backends.smtp.EmailBackend.open", fail)
        assert mail.check_connection() == code
        ok, text = svc.check_email(admin_user)
        assert ok is False
        assert "smtp.example.com" not in text

    def test_the_connection_test_succeeds_and_needs_a_server(
        self, admin_user: User, monkeypatch: Any
    ) -> None:
        assert svc.check_email(admin_user)[0] is False
        svc.update(admin_user, {"email_host": "smtp.example.com"})
        monkeypatch.setattr("django.core.mail.backends.smtp.EmailBackend.open", lambda self: True)
        assert svc.check_email(admin_user) == (True, "Connected to the mail server.")


class TestWriting:
    def test_only_administrators_write(self, alice: User) -> None:
        with pytest.raises(PermissionDenied):
            svc.update(alice, {"invitation_lifetime_days": 3})
        with pytest.raises(PermissionDenied):
            svc.reset(alice, "invitation_lifetime_days")
        with pytest.raises(PermissionDenied):
            svc.check_email(alice)

    def test_a_locked_setting_is_refused_and_names_its_variable(self, admin_user: User) -> None:
        with locked("invitation_lifetime_days", HOUSECAIRN_INVITATION_LIFETIME_DAYS=3):
            with pytest.raises(ValidationError, match="HOUSECAIRN_INVITATION_LIFETIME_DAYS"):
                svc.update(admin_user, {"invitation_lifetime_days": 30})
            with pytest.raises(ValidationError, match="HOUSECAIRN_INVITATION_LIFETIME_DAYS"):
                svc.reset(admin_user, "invitation_lifetime_days")
        assert not SettingValue.objects.exists()

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("email_port", 70000),
            ("email_port", "abc"),
            ("email_port", True),
            ("email_timeout", 0),
            ("invitation_lifetime_days", 91),
            ("signup_pow_bits", 7),
            ("signup_open", "yes"),
            ("oidc_signup", "invite"),
            ("site_url", "ftp://example.com"),
            ("site_url", "https://example.com/path"),
            ("signup_blocked_domains", "not a domain"),
            ("email_host", "smtp.example.com\r\nBcc: x"),
            ("email_host", "bad host"),
            ("default_from_email", "no-address"),
            ("email_host_password", ""),
            ("nonexistent", 1),
        ],
    )
    def test_an_invalid_value_is_refused_and_nothing_is_stored(
        self, admin_user: User, key: str, value: Any
    ) -> None:
        with pytest.raises(ValidationError) as caught:
            svc.update(admin_user, {key: value})
        assert key in caught.value.message_dict
        assert not SettingValue.objects.exists()

    def test_the_whole_change_or_nothing(self, admin_user: User) -> None:
        with pytest.raises(ValidationError):
            svc.update(admin_user, {"invitation_lifetime_days": 30, "email_port": 0})
        assert config.get_setting("invitation_lifetime_days") == 7

    def test_open_sign_up_needs_a_mail_server(self, admin_user: User) -> None:
        with pytest.raises(ValidationError, match="SMTP server"):
            svc.update(admin_user, {"signup_open": True})
        svc.update(admin_user, {"signup_open": True, "email_host": "smtp.example.com"})
        with pytest.raises(ValidationError, match="SMTP server"):
            svc.update(admin_user, {"email_host": ""})
        assert config.get_setting("email_host") == "smtp.example.com"

    def test_restoring_no_mail_server_is_refused_while_sign_up_is_open(
        self, admin_user: User
    ) -> None:
        svc.update(admin_user, {"signup_open": True, "email_host": "smtp.example.com"})
        with pytest.raises(ValidationError, match="SMTP server") as caught:
            svc.reset(admin_user, "email_host")
        assert "email_host" in caught.value.message_dict
        assert config.get_setting("email_host") == "smtp.example.com"
        assert not AuditEvent.objects.filter(action="settings.reset").exists()
        # Closing sign-up first makes the same reset possible.
        assert svc.reset(admin_user, "signup_open") is True
        assert svc.reset(admin_user, "email_host") is True

    def test_restoring_no_mail_server_is_refused_while_a_variable_opens_sign_up(
        self, admin_user: User
    ) -> None:
        with locked("signup_open", HOUSECAIRN_SIGNUP_OPEN=True):
            svc.update(admin_user, {"email_host": "smtp.example.com"})
            with pytest.raises(ValidationError, match="SMTP server"):
                svc.reset(admin_user, "email_host")
            assert config.get_setting("email_host") == "smtp.example.com"

    def test_the_site_url_loses_its_trailing_slash(self, admin_user: User) -> None:
        svc.update(admin_user, {"site_url": "https://home.example.com/"})
        assert config.get_setting("site_url") == "https://home.example.com"

    def test_the_new_address_is_used_for_links(self, admin_user: User, rf: Any) -> None:
        from housecairn.homes.scoping import site_url

        svc.update(admin_user, {"site_url": "https://home.example.com"})
        assert site_url(rf.get("/")) == "https://home.example.com"

    def test_each_change_is_in_the_audit_log_with_old_and_new_values(
        self, admin_user: User
    ) -> None:
        svc.update(admin_user, {"email_port": 2525})
        svc.update(admin_user, {"email_port": 465})
        svc.reset(admin_user, "email_port")
        entries = list(AuditEvent.objects.order_by("created_at", "id"))
        assert [e.action for e in entries] == [
            "settings.changed",
            "settings.changed",
            "settings.reset",
        ]
        assert entries[0].detail == {"setting": "email_port", "old": "587", "new": "2525"}
        assert entries[1].detail == {"setting": "email_port", "old": "2525", "new": "465"}
        assert all(e.actor == admin_user and e.scope == "instance" for e in entries)
        assert entries[0].label == "Setting email_port changed from 587 to 2525"
        assert "reset to its default" in entries[2].label

    def test_a_list_is_audited_as_text(self, admin_user: User) -> None:
        svc.update(admin_user, {"signup_blocked_domains": "a.example, b.example"})
        entry = AuditEvent.objects.get(action="settings.changed")
        assert entry.detail["new"] == "a.example, b.example"
        assert entry.detail["old"] == "(empty)"


class TestSecrets:
    def test_the_secret_is_encrypted_at_rest(self, admin_user: User) -> None:
        svc.update(admin_user, {"email_host_password": SECRET})
        row = SettingValue.objects.get(key="email_host_password")
        assert row.is_secret
        assert SECRET not in row.value
        assert row.value.startswith("v1:")
        assert crypto.decrypt(row.value) == SECRET

    def test_the_secret_is_never_audited(self, admin_user: User) -> None:
        svc.update(admin_user, {"email_host_password": SECRET})
        svc.update(admin_user, {"email_host_password": SECRET + "2"})
        svc.reset(admin_user, "email_host_password")
        actions = list(
            AuditEvent.objects.order_by("created_at", "id").values_list("action", "detail")
        )
        assert actions == [
            ("settings.secret_changed", {"setting": "email_host_password"}),
            ("settings.secret_changed", {"setting": "email_host_password"}),
            ("settings.reset", {"setting": "email_host_password"}),
        ]
        assert SECRET not in json.dumps(actions)

    def test_a_changed_key_makes_the_secret_unreadable_not_fatal(
        self, admin_user: User, caplog: Any
    ) -> None:
        svc.update(admin_user, {"email_host_password": SECRET})
        with override_settings(SECRET_KEY="another-key-" + "y" * 40):
            config.invalidate()
            state = config.describe("email_host_password")
            assert state.unreadable is True
            assert state.is_set is False
            with caplog.at_level(logging.WARNING, logger="housecairn.settings"):
                assert config.get_setting("email_host_password") == ""
            assert SECRET not in caplog.text

    def test_a_fallback_key_still_reads_it(self, admin_user: User) -> None:
        from django.conf import settings

        svc.update(admin_user, {"email_host_password": SECRET})
        old = settings.SECRET_KEY
        with override_settings(SECRET_KEY="rotated-key-" + "z" * 40, SECRET_KEY_FALLBACKS=[old]):
            config.invalidate()
            assert config.get_setting("email_host_password") == SECRET
            assert config.describe("email_host_password").unreadable is False

    def test_garbage_is_unreadable(self) -> None:
        for stored in ("plain", "v1:not-a-token", "v1:"):
            with pytest.raises(crypto.SecretUnreadableError):
                crypto.decrypt(stored)


class TestWebScreen:
    def test_an_administrator_sees_the_sections_and_the_server_variables(
        self, admin_client: Client
    ) -> None:
        response = admin_client.get(reverse(WEB))
        assert response.status_code == 200
        page = response.text
        for text in ("Public address", "Open sign-up", "Outgoing email", "SMTP server", "Server"):
            assert text in page
        assert "ALLOWED_HOSTS" in page
        assert "Restore the default" not in page

    def test_the_screen_never_shows_the_secret_key_nor_a_database_address(
        self, admin_client: Client
    ) -> None:
        from django.conf import settings

        page = admin_client.get(reverse(WEB)).text
        assert settings.SECRET_KEY not in page
        engine = str(settings.DATABASES["default"]["ENGINE"]).rsplit(".", 1)[-1]
        assert engine in page
        server_part = page.split("<h2>Server</h2>")[1]
        assert "DATABASE_URL" in server_part
        assert "://" not in server_part  # no address with credentials

    def test_save_a_section_then_restore_a_default(self, admin_client: Client) -> None:
        response = post(admin_client, "invitations", invitation_lifetime_days="30")
        assert response.status_code == 302
        assert config.get_setting("invitation_lifetime_days") == 30
        page = admin_client.get(reverse(WEB)).text
        assert 'value="30"' in page
        assert "Restore the default" in page
        response = post(admin_client, "invitations", reset="invitation_lifetime_days")
        assert response.status_code == 302
        assert config.get_setting("invitation_lifetime_days") == 7

    def test_a_locked_field_is_read_only_with_its_value_and_variable(
        self, admin_client: Client
    ) -> None:
        with locked("invitation_lifetime_days", HOUSECAIRN_INVITATION_LIFETIME_DAYS=3):
            page = admin_client.get(reverse(WEB)).text
        field = re.search(r'<input[^>]*id="locked-invitation_lifetime_days"[^>]*>', page)
        assert field is not None
        tag = field.group(0)
        assert "readonly" in tag
        assert 'aria-readonly="true"' in tag
        assert 'value="3"' in tag
        assert 'aria-describedby="env-invitation_lifetime_days"' in tag
        assert "HOUSECAIRN_INVITATION_LIFETIME_DAYS" in page
        assert "/administration/settings/" in page
        assert 'name="invitation_lifetime_days"' not in page

    def test_a_locked_boolean_is_a_disabled_box_in_the_right_state(
        self, admin_client: Client
    ) -> None:
        with locked("email_use_ssl", EMAIL_USE_SSL=True):
            page = admin_client.get(reverse(WEB)).text
        tag = re.search(r'<input[^>]*id="locked-email_use_ssl"[^>]*>', page)
        assert tag is not None
        assert "disabled" in tag.group(0)
        assert "checked" in tag.group(0)

    def test_a_locked_secret_says_set_without_the_value(self, admin_client: Client) -> None:
        with locked("email_host_password", EMAIL_HOST_PASSWORD=SECRET):
            page = admin_client.get(reverse(WEB)).text
        assert SECRET not in page
        tag = re.search(r'<input[^>]*id="locked-email_host_password"[^>]*>', page)
        assert tag is not None
        assert 'value="set"' in tag.group(0)

    def test_a_write_to_a_locked_setting_is_ignored_by_the_screen(
        self, admin_client: Client
    ) -> None:
        with locked("invitation_lifetime_days", HOUSECAIRN_INVITATION_LIFETIME_DAYS=3):
            response = post(admin_client, "invitations", invitation_lifetime_days="30")
            assert response.status_code == 302
            assert config.get_setting("invitation_lifetime_days") == 3
            response = post(admin_client, "invitations", reset="invitation_lifetime_days")
            assert response.status_code == 302
        assert not SettingValue.objects.exists()
        assert not AuditEvent.objects.exists()

    def test_an_invalid_value_is_refused_with_a_message(self, admin_client: Client) -> None:
        response = post(admin_client, "email", email_port="70000", email_timeout="15")
        assert response.status_code == 422
        assert "Ensure this value is less than or equal to 65535" in response.text
        assert config.get_setting("email_port") == 587

    def test_a_refused_combination_is_shown_on_the_field(self, admin_client: Client) -> None:
        response = post(admin_client, "signup", signup_open="on", signup_pow_bits="16")
        assert response.status_code == 422
        assert "set the SMTP server first" in response.text
        assert config.get_setting("signup_open") is False

    @pytest.mark.parametrize("by_variable", [False, True], ids=["database", "variable"])
    def test_restoring_no_mail_server_is_refused_with_the_message(
        self, admin_client: Client, admin_user: User, by_variable: bool
    ) -> None:
        opened = (
            locked("signup_open", HOUSECAIRN_SIGNUP_OPEN=True)
            if by_variable
            else override_settings()
        )
        with opened:
            if by_variable:
                svc.update(admin_user, {"email_host": "smtp.example.com"})
            else:
                svc.update(admin_user, {"signup_open": True, "email_host": "smtp.example.com"})
            response = post(admin_client, "email", reset="email_host")
            assert response.status_code == 302
            page = admin_client.get(reverse(WEB)).text
            assert "set the SMTP server first" in page
            assert "Default restored." not in page
            assert config.get_setting("email_host") == "smtp.example.com"

    def test_an_empty_secret_keeps_the_stored_one(
        self, admin_client: Client, admin_user: User
    ) -> None:
        svc.update(admin_user, {"email_host_password": SECRET})
        response = post(admin_client, "email", email_host_password="", email_port="587")
        assert response.status_code == 302
        assert config.get_setting("email_host_password") == SECRET
        assert "A secret is stored." in admin_client.get(reverse(WEB)).text

    def test_the_connection_test_reports_and_is_rate_limited(
        self, admin_client: Client, admin_user: User, monkeypatch: Any
    ) -> None:
        svc.update(admin_user, {"email_host": "smtp.example.com"})
        monkeypatch.setattr("django.core.mail.backends.smtp.EmailBackend.open", lambda self: True)
        response = post(admin_client, "email", test_email="1")
        assert response.status_code == 302
        assert "Connected to the mail server." in admin_client.get(reverse(WEB)).text
        for _ in range(6):
            post(admin_client, "email", test_email="1")
        page = admin_client.get(reverse(WEB)).text
        assert "Too many tests" in page

    def test_an_unknown_section_is_a_404(self, admin_client: Client) -> None:
        assert admin_client.post(reverse(WEB), {"section": "nothing"}).status_code == 404

    def test_the_screen_is_linked_from_the_overview(self, admin_client: Client) -> None:
        assert reverse(WEB) in admin_client.get(reverse("instance:overview")).text


class TestWhoMayCome:
    def test_a_member_gets_a_404_everywhere(self, client: Client, alice: User) -> None:
        recent(client, alice)
        assert client.get(reverse(WEB)).status_code == 404
        assert (
            client.post(reverse(WEB), {"section": "email", "email_port": "25"}).status_code == 404
        )
        assert config.get_setting("email_port") == 587

    def test_the_api_refuses_a_member_and_an_anonymous_client(
        self, client: Client, api_client: APIClient, alice: User
    ) -> None:
        assert api_client.get(reverse(API)).status_code in {401, 403}
        recent(client, alice)
        for response in (
            client.get(reverse(API)),
            client.patch(
                reverse(API), json.dumps({"email_port": 25}), content_type="application/json"
            ),
            client.delete(reverse("api-v1:instance-setting-reset", args=["email_port"])),
            client.post(reverse("api-v1:instance-email-test")),
        ):
            assert response.status_code == 403
        assert not SettingValue.objects.exists()

    def test_a_token_never_serves_it_even_an_administrators(
        self, api_client: APIClient, admin_user: User
    ) -> None:
        home = home_services.create_home(admin_user, name="Own")
        _token, raw = token_services.issue_token(
            admin_user, name="all", scopes=["read", "write"], homes=[home]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert api_client.get(reverse(API)).status_code == 403
        assert api_client.patch(reverse(API), {"email_port": 25}).status_code == 403
        assert (
            api_client.delete(
                reverse("api-v1:instance-setting-reset", args=["email_port"])
            ).status_code
            == 403
        )
        assert api_client.post(reverse("api-v1:instance-email-test")).status_code == 403
        assert not SettingValue.objects.exists()

    def test_the_administrator_still_reads_no_home(
        self, admin_client: Client, admin_api: APIClient, bob_home: Home
    ) -> None:
        svc_page = admin_client.get(reverse(WEB)).text
        listing = admin_api.get(reverse(API)).text
        audit = admin_client.get(reverse("instance:audit")).text
        for text in (svc_page, listing, audit):
            assert bob_home.name not in text
            assert str(bob_home.id) not in text


class TestRecentSignIn:
    def test_a_change_without_a_recent_sign_in_goes_to_the_confirmation(
        self, client: Client, admin_user: User
    ) -> None:
        recent(client, admin_user, age=3600)
        response = post(client, "invitations", invitation_lifetime_days="30")
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("account_reauthenticate"))
        assert "next=" in response["Location"]
        assert config.get_setting("invitation_lifetime_days") == 7

    def test_a_forced_login_without_a_record_is_not_recent(
        self, client: Client, admin_user: User
    ) -> None:
        client.force_login(admin_user)
        response = post(client, "invitations", invitation_lifetime_days="30")
        assert response["Location"].startswith(reverse("account_reauthenticate"))

    def test_the_secret_is_not_kept_in_the_session_while_confirming(
        self, client: Client, admin_user: User
    ) -> None:
        recent(client, admin_user, age=3600)
        post(client, "email", email_host_password=SECRET, email_port="587")
        assert SECRET not in json.dumps(dict(client.session.items()), default=str)

    def test_reading_needs_no_recent_sign_in(self, client: Client, admin_user: User) -> None:
        recent(client, admin_user, age=3600)
        assert client.get(reverse(WEB)).status_code == 200

    def test_the_api_asks_for_it_with_a_code(self, api_client: APIClient, admin_user: User) -> None:
        recent(api_client, admin_user, age=3600)
        for response in (
            api_client.patch(reverse(API), {"email_port": 25}),
            api_client.delete(reverse("api-v1:instance-setting-reset", args=["email_port"])),
        ):
            assert response.status_code == 403
            assert response.json()["code"] == "reauthentication_required"
        assert api_client.get(reverse(API)).status_code == 200
        assert config.get_setting("email_port") == 587

    def test_an_account_that_cannot_re_authenticate_counts_as_recent(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        sso_admin = make_user("sso@example.com", is_staff=True, is_superuser=True)
        sso_admin.set_unusable_password()
        sso_admin.save()
        client.force_login(sso_admin)
        assert post(client, "invitations", invitation_lifetime_days="30").status_code == 302
        assert config.get_setting("invitation_lifetime_days") == 30


class TestApi:
    def test_the_listing_says_value_default_source_and_variable(self, admin_api: APIClient) -> None:
        response = admin_api.get(reverse(API))
        assert response.status_code == 200
        by_key = {s["key"]: s for s in response.json()["settings"]}
        assert set(by_key) == set(registry.SETTINGS)
        port = by_key["email_port"]
        assert port["value"] == 587
        assert port["default"] == 587
        assert port["source"] == "default"
        assert port["locked"] is False
        assert port["environment_variable"] == "EMAIL_PORT"
        assert port["reload"] == "live"
        assert (port["minimum"], port["maximum"]) == (1, 65535)
        assert by_key["email_host_password"]["secret_set"] is False
        assert by_key["email_host_password"]["value"] is None
        assert by_key["oidc_signup"]["choices"] == ["closed", "open"]

    def test_patch_then_delete(self, admin_api: APIClient) -> None:
        response = admin_api.patch(
            reverse(API), {"invitation_lifetime_days": 30, "signup_blocked_domains": ["a.example"]}
        )
        assert response.status_code == 200
        by_key = {s["key"]: s for s in response.json()["settings"]}
        assert by_key["invitation_lifetime_days"]["value"] == 30
        assert by_key["invitation_lifetime_days"]["source"] == "database"
        assert by_key["signup_blocked_domains"]["value"] == ["a.example"]
        response = admin_api.delete(
            reverse("api-v1:instance-setting-reset", args=["invitation_lifetime_days"])
        )
        assert response.status_code == 204
        assert config.get_setting("invitation_lifetime_days") == 7

    def test_a_locked_setting_answers_409_and_changes_nothing(self, admin_api: APIClient) -> None:
        with locked("email_port", EMAIL_PORT=2525):
            by_key = {s["key"]: s for s in admin_api.get(reverse(API)).json()["settings"]}
            assert by_key["email_port"]["locked"] is True
            assert by_key["email_port"]["source"] == "environment"
            assert by_key["email_port"]["value"] == 2525
            response = admin_api.patch(reverse(API), {"email_port": 25, "email_timeout": 20})
            assert response.status_code == 409
            assert response.json()["locked"] == ["email_port"]
            response = admin_api.delete(
                reverse("api-v1:instance-setting-reset", args=["email_port"])
            )
            assert response.status_code == 409
        assert not SettingValue.objects.exists()

    def test_invalid_input_is_a_400(self, admin_api: APIClient) -> None:
        for body in (
            {"email_port": 70000},
            {"email_port": "abc"},
            {"signup_open": "maybe"},
            {"nonexistent": 1},
            {"oidc_signup": "invite"},
            {"signup_open": True},  # no mail server
            {"signup_blocked_domains": ["not a domain"]},
        ):
            response = admin_api.patch(reverse(API), body)
            assert response.status_code == 400, body
        assert not SettingValue.objects.exists()
        assert admin_api.patch(reverse(API), [1], format="json").status_code == 400

    @pytest.mark.parametrize("by_variable", [False, True], ids=["database", "variable"])
    def test_restoring_no_mail_server_is_a_400_while_sign_up_is_open(
        self, admin_api: APIClient, admin_user: User, by_variable: bool
    ) -> None:
        opened = (
            locked("signup_open", HOUSECAIRN_SIGNUP_OPEN=True)
            if by_variable
            else override_settings()
        )
        with opened:
            if by_variable:
                svc.update(admin_user, {"email_host": "smtp.example.com"})
            else:
                svc.update(admin_user, {"signup_open": True, "email_host": "smtp.example.com"})
            response = admin_api.delete(
                reverse("api-v1:instance-setting-reset", args=["email_host"])
            )
            assert response.status_code == 400
            assert "set the SMTP server first" in response.json()["email_host"][0]
            assert config.get_setting("email_host") == "smtp.example.com"

    def test_an_unknown_setting_cannot_be_reset(self, admin_api: APIClient) -> None:
        response = admin_api.delete(reverse("api-v1:instance-setting-reset", args=["nope"]))
        assert response.status_code == 404

    def test_the_connection_test(
        self, admin_api: APIClient, admin_user: User, monkeypatch: Any
    ) -> None:
        response = admin_api.post(reverse("api-v1:instance-email-test"))
        assert response.json()["ok"] is False
        svc.update(admin_user, {"email_host": "smtp.example.com"})
        monkeypatch.setattr("django.core.mail.backends.smtp.EmailBackend.open", lambda self: True)
        assert admin_api.post(reverse("api-v1:instance-email-test")).json()["ok"] is True
        for _ in range(6):
            response = admin_api.post(reverse("api-v1:instance-email-test"))
        assert response.status_code == 429

    def test_the_schema_describes_the_endpoints(self, admin_api: APIClient) -> None:
        schema = admin_api.get(reverse("api-schema"), HTTP_ACCEPT="application/json").json()
        assert "/api/v1/instance/settings/" in schema["paths"]
        assert "patch" in schema["paths"]["/api/v1/instance/settings/"]
        assert "/api/v1/instance/settings/{key}/" in schema["paths"]
        write = schema["components"]["schemas"]["PatchedSettingsUpdateRequest"]["properties"]
        assert "email_host_password" in write
        read = json.dumps(schema["components"]["schemas"].get("InstanceSetting", {}))
        assert "secret_set" in read


class TestSecretsStayInside:
    """Nothing the instance shows or writes carries the secret: searched for in clear."""

    def test_no_surface_carries_the_secret(
        self,
        admin_client: Client,
        admin_api: APIClient,
        admin_user: User,
        caplog: Any,
        monkeypatch: Any,
        alice: User,
        alice_home: Home,
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            assert post(admin_client, "email", email_host_password=SECRET).status_code == 302
            post(admin_client, "email", email_host_password=SECRET, email_port="not a number")
            admin_api.patch(reverse(API), {"email_host_password": SECRET + "-api"})
            outputs = [
                admin_client.get(reverse(WEB)).text,
                admin_api.get(reverse(API)).text,
                admin_client.get(reverse("instance:audit")).text,
                admin_api.get(reverse("api-v1:instance-audit-list")).text,
                admin_api.patch(reverse(API), {"email_port": 25}).text,
                admin_client.get(reverse("admin:index")).text,
            ]
            monkeypatch.setattr(
                "django.core.mail.backends.smtp.EmailBackend.open", lambda self: True
            )
            outputs.append(admin_api.post(reverse("api-v1:instance-email-test")).text)
            # The export of a home, and the audit rows themselves.
            recent(admin_client, alice)
            export = admin_client.post(reverse("homes:export", kwargs={"home_id": alice_home.id}))
            archive = zipfile.ZipFile(BytesIO(b"".join(export.streaming_content)))
            outputs += [archive.read(name).decode() for name in archive.namelist()]
        outputs.append(
            json.dumps(list(AuditEvent.objects.values_list("action", "detail")), default=str)
        )
        outputs.append(caplog.text)
        for output in outputs:
            assert SECRET not in output
        assert config.get_setting("email_host_password") == SECRET + "-api"

    def test_the_value_is_not_in_the_database_in_clear(self, admin_user: User) -> None:
        svc.update(admin_user, {"email_host_password": SECRET})
        assert not SettingValue.objects.filter(value__contains=SECRET).exists()


class TestDocumentation:
    def test_the_table_of_settings_is_in_the_page(self) -> None:
        page = (Path(__file__).parents[1] / "docs/administration/settings.md").read_text()
        start, end = settings_table.START, settings_table.END
        assert start in page
        assert end in page
        shown = page.split(start)[1].split(end)[0].strip()
        assert shown == settings_table.table(), (
            "docs/administration/settings.md is out of date: run `manage.py settings_table` "
            "and paste the table between the markers."
        )

    def test_every_setting_names_a_variable_once_and_is_in_the_page(self) -> None:
        page = (Path(__file__).parents[1] / "docs/administration/settings.md").read_text()
        envs = [s.env for s in registry.SETTINGS.values()]
        assert len(envs) == len(set(envs))
        for setting in registry.SETTINGS.values():
            assert f"`{setting.env}`" in page, setting.key

    def test_the_command_prints_the_table(self, capsys: Any) -> None:
        call_command("settings_table")
        assert capsys.readouterr().out.strip() == settings_table.table()

    def test_the_server_variables_are_not_settings(self) -> None:
        names = {s.env for s in registry.SETTINGS.values()}
        assert not names & {env for env, _label in registry.SERVER_VARIABLES}


@pytest.mark.django_db(transaction=True)
def test_the_migration_can_be_undone_and_redone() -> None:
    call_command("migrate", "instance", "0001", verbosity=0)
    from django.db import connection

    assert "instance_settingvalue" not in connection.introspection.table_names()
    call_command("migrate", "instance", verbosity=0)
    assert "instance_settingvalue" in connection.introspection.table_names()
