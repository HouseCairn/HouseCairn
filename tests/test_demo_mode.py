"""The demonstration mode (`HOUSECAIRN_DEMO`, docs/adr/0071).

Each refusal is checked where a visitor would try it, on the screen and through the API,
with what it must leave untouched. `HOUSECAIRN_DEMO` false changes nothing.
"""

import datetime
import io
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from allauth.account.internal.userkit import user_id_to_str
from allauth.account.models import EmailAddress
from cryptography.hazmat.primitives.asymmetric import ec
from django.core import mail as django_mail
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.management import CommandError, call_command
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from housecairn.accounts import services as account_services
from housecairn.accounts import setup
from housecairn.accounts.models import User
from housecairn.demo import mode, reset, tasks
from housecairn.homes import quotas, restore
from housecairn.homes import services as home_services
from housecairn.homes.models import Home, Membership, Role
from housecairn.instance import config, mail, providers, ratelimits, settings_services
from housecairn.instance import services as instance_services
from housecairn.instance.models import InstanceInvitation, OidcProvider, SettingValue
from housecairn.notifications import devices, outbound, webpush
from housecairn.notifications import services as notifications
from housecairn.notifications.models import Channel, Device
from housecairn.projects.models import Project
from housecairn.rooms.models import Room
from housecairn.tasks.models import Task

pytestmark = pytest.mark.django_db

URL = "tgram://123456789:AAbbCCddEEffGGhhIIjjKKllMMnnOOppQQrr/987654321"


@pytest.fixture
def media(settings: Any, tmp_path: Path) -> Path:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_ROOT.mkdir()
    return Path(settings.MEDIA_ROOT)


@pytest.fixture
def demo(settings: Any, media: Path) -> Iterator[None]:
    settings.HOUSECAIRN_DEMO = True
    config.invalidate()
    reset.reset(language="en", today=datetime.date(2026, 11, 12))
    yield
    config.invalidate()


def admin() -> User:
    return User.objects.get(email=mode.ADMIN_EMAIL)


def member() -> User:
    return User.objects.get(email=mode.USER_EMAIL)


def signed_in(client: Client | APIClient, user: User) -> Client | APIClient:
    """Signed in recently, as allauth records it, so that settings screens accept a change."""
    client.force_login(user)
    session = client.session
    session["account_authentication_methods"] = [{"method": "password", "at": time.time()}]
    session["account_authentication_methods_user"] = user_id_to_str(user)
    session.save()
    return client


def state() -> dict[str, Any]:
    """What the reset is meant to make, compared between two resets (identifiers aside)."""
    home = Home.objects.get()
    return {
        "users": sorted(
            User.objects.values_list("email", "is_staff", "is_superuser", "display_name")
        ),
        "addresses": sorted(EmailAddress.objects.values_list("email", "verified", "primary")),
        "homes": list(Home.objects.values_list("name", flat=True)),
        "roles": sorted(Membership.objects.values_list("user__email", "role")),
        "rooms": sorted(Room.objects.filter(home=home).values_list("name", flat=True)),
        "tasks": sorted(Task.objects.filter(home=home).values_list("title", flat=True)),
        "projects": sorted(Project.objects.filter(home=home).values_list("title", flat=True)),
        "settings": list(SettingValue.objects.values_list("key", flat=True)),
    }


def padded_archive(home: Home, size: int) -> bytes:
    """The archive of the home with a manifest of `size` bytes: blanks after the JSON."""
    import zipfile

    from housecairn.homes import exports

    source, _name = exports.build_archive(home)
    out = io.BytesIO()
    with zipfile.ZipFile(source) as read, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as write:
        for info in read.infolist():
            data = read.read(info)
            if info.filename == exports.MANIFEST:
                data = data + b" " * (size - len(data))
            write.writestr(info.filename, data)
    return out.getvalue()


class TestOff:
    """`HOUSECAIRN_DEMO` false, the default: nothing changes."""

    def test_the_default_is_off(self) -> None:
        assert mode.is_on() is False

    def test_reset_demo_refuses_to_run(self, alice: User) -> None:
        with pytest.raises(CommandError, match="HOUSECAIRN_DEMO"):
            call_command("reset_demo")
        assert User.objects.filter(pk=alice.pk).exists()

    def test_reset_refuses_to_run(self, alice: User) -> None:
        with pytest.raises(reset.DemoOffError):
            reset.reset()
        assert User.objects.filter(pk=alice.pk).exists()

    def test_the_public_addresses_are_ordinary_accounts(self, make_user: Any) -> None:
        user = make_user(mode.ADMIN_EMAIL)
        user.set_password("another-password-of-the-owner")
        user.email = "renamed@example.com"
        user.save()
        account_services.delete_account(user)
        assert not User.objects.filter(pk=user.pk).exists()

    def test_settings_are_not_forced(self, admin_user: User) -> None:
        settings_services.update(admin_user, {"link_preview_enabled": True})
        assert config.get_setting("link_preview_enabled") is True
        assert config.source("file_max_bytes") == config.Source.DEFAULT

    def test_mail_is_sent(self) -> None:
        sent = mail.EmailBackend().send_messages([EmailMessage("s", "b", to=["a@example.com"])])
        assert sent == 1

    def test_no_banner(self, client: Client) -> None:
        page = client.get(reverse("account_login")).content.decode()
        assert mode.PASSWORD not in page
        assert "Demonstration instance" not in page

    def test_no_schedule(self) -> None:
        from django_q.models import Schedule

        tasks.schedule()
        assert not Schedule.objects.filter(name=tasks.SCHEDULE).exists()

    def test_the_settings_screen_has_no_fieldset(self, client: Client, admin_user: User) -> None:
        """The disabled fieldset of the demonstration would change the look of the form."""
        signed_in(client, admin_user)
        page = client.get(reverse("instance:settings", kwargs={"section": "instance"}))
        assert page.status_code == 200
        text = page.content.decode()
        assert "<form" in text
        assert "<fieldset" not in text
        assert "</fieldset>" not in text
        assert "demo-read-only" not in text


@pytest.fixture
def admin_user(make_user: Any) -> User:
    return make_user("root@example.com", is_staff=True, is_superuser=True)


class TestReset:
    def test_accounts_and_home(self, demo: None) -> None:
        assert account_services.is_instance_admin(admin())
        assert not account_services.is_instance_admin(member())
        home = Home.objects.get()
        assert home.memberships.get(user=admin()).role == Role.OWNER
        assert home.memberships.get(user=member()).role == Role.MEMBER
        assert admin().check_password(mode.PASSWORD)
        assert member().check_password(mode.PASSWORD)
        assert EmailAddress.objects.filter(verified=True, primary=True).count() == 2
        assert Task.objects.filter(home=home).exists()
        assert Project.objects.filter(home=home).exists()

    def test_twice_gives_the_same_state(self, demo: None) -> None:
        first = state()
        reset.reset(language="en", today=datetime.date(2026, 11, 12))
        assert state() == first

    def test_what_was_made_in_between_is_gone(self, demo: None, make_user: Any) -> None:
        first = state()
        with mode.reset_context():
            stranger = make_user("stranger@example.com")
        extra = home_services.create_home(member(), name="Visitor's house")
        SettingValue.objects.create(key="instance_name", value='"Defaced"')
        reset.reset(language="en", today=datetime.date(2026, 11, 12))
        assert state() == first
        assert not User.objects.filter(pk=stranger.pk).exists()
        assert not Home.all_objects.filter(pk=extra.pk).exists()

    def test_uploaded_files_are_removed(self, demo: None, media: Path) -> None:
        uploaded = media / "homes" / str(Home.objects.get().pk) / "photo.jpg"
        uploaded.parent.mkdir(parents=True)
        uploaded.write_bytes(b"x" * 100)
        reset.reset(language="en")
        assert not uploaded.exists()
        assert list(media.iterdir()) == []

    def test_command_if_empty_leaves_an_instance_with_accounts(self, demo: None) -> None:
        home = Home.objects.get()
        call_command("reset_demo", "--if-empty")
        assert Home.objects.get().pk == home.pk

    def test_command_on_an_empty_instance(self, settings: Any, media: Path) -> None:
        settings.HOUSECAIRN_DEMO = True
        call_command("reset_demo", "--if-empty", "--language", "fr")
        assert User.objects.count() == 2
        assert Home.objects.get().name

    def test_schedule_at_three_in_paris(self, demo: None) -> None:
        from django_q.models import Schedule

        tasks.schedule()
        found = Schedule.objects.get(name=tasks.SCHEDULE)
        local = found.next_run.astimezone(datetime.UTC).astimezone(
            __import__("zoneinfo").ZoneInfo("Europe/Paris")
        )
        assert (local.hour, local.minute) == (3, 0)
        assert found.func == "housecairn.demo.tasks.nightly_reset"

    def test_next_reset_follows_summer_time(self) -> None:
        winter = tasks.next_reset(datetime.datetime(2026, 1, 10, 12, tzinfo=datetime.UTC))
        summer = tasks.next_reset(datetime.datetime(2026, 7, 10, 12, tzinfo=datetime.UTC))
        assert winter.astimezone(datetime.UTC).hour == 2
        assert summer.astimezone(datetime.UTC).hour == 1
        just_before = datetime.datetime(2026, 7, 10, 0, 59, tzinfo=datetime.UTC)
        assert tasks.next_reset(just_before).date() == datetime.date(2026, 7, 10)


class TestSettingsReadOnly:
    def test_the_screen_shows_them_disabled(self, demo: None, client: Client) -> None:
        signed_in(client, admin())
        page = client.get(reverse("instance:settings", kwargs={"section": "instance"}))
        assert page.status_code == 200
        assert "<fieldset disabled>" in page.content.decode()

    def test_the_screen_refuses_a_change(self, demo: None, client: Client) -> None:
        signed_in(client, admin())
        answer = client.post(
            reverse("instance:settings", kwargs={"section": "instance"}),
            {"instance_name": "Defaced"},
            follow=True,
        )
        assert mode.settings_read_only() in answer.content.decode()
        assert not SettingValue.objects.exists()

    def test_the_api_refuses_a_change(self, demo: None, api_client: APIClient) -> None:
        signed_in(api_client, admin())
        answer = api_client.patch(
            reverse("api-v1:instance-settings"), {"instance_name": "Defaced"}, format="json"
        )
        assert answer.status_code == 403
        assert answer.json()["code"] == "demo"
        assert not SettingValue.objects.exists()

    def test_the_api_refuses_a_reset(self, demo: None, api_client: APIClient) -> None:
        signed_in(api_client, admin())
        answer = api_client.delete(
            reverse("api-v1:instance-setting-reset", kwargs={"key": "instance_name"})
        )
        assert answer.status_code == 403
        assert answer.json()["code"] == "demo"

    def test_the_service_refuses_a_reset(self, demo: None) -> None:
        with pytest.raises(mode.DemoRefusedError):
            settings_services.reset(admin(), "instance_name")

    def test_forced_values_win_over_the_database(self, demo: None) -> None:
        SettingValue.objects.create(key="signup_open", value="true")
        config.invalidate()
        assert config.get_setting("signup_open") is False
        assert config.describe("signup_open").locked
        assert config.source("signup_open") == config.Source.DEMO

    def test_the_api_says_where_a_forced_value_comes_from(
        self, demo: None, api_client: APIClient
    ) -> None:
        signed_in(api_client, admin())
        rows = api_client.get(reverse("api-v1:instance-settings")).json()["settings"]
        row = next(r for r in rows if r["key"] == "file_max_bytes")
        assert (row["source"], row["locked"], row["value"]) == ("demo", True, mode.FILE_MAX_BYTES)

    def test_providers_cannot_be_added(self, demo: None, api_client: APIClient) -> None:
        signed_in(api_client, admin())
        answer = api_client.post(
            reverse("api-v1:instance-provider-list"),
            {"slug": "sso", "name": "SSO", "issuer": "https://id.example.com", "client_id": "x"},
            format="json",
        )
        assert answer.status_code == 403
        assert not OidcProvider.objects.exists()

    def test_providers_screen_refuses(self, demo: None, client: Client) -> None:
        signed_in(client, admin())
        data = {"slug": "sso", "name": "SSO", "issuer": "https://id.example.com", "client_id": "x"}
        answer = client.post(reverse("instance:providers"), data, follow=True)
        assert mode.settings_read_only() in answer.content.decode()
        assert not OidcProvider.objects.exists()


class TestNothingSent:
    def test_no_email(self, demo: None) -> None:
        sent = mail.EmailBackend().send_messages([EmailMessage("s", "b", to=["a@example.com"])])
        assert sent == 0
        assert django_mail.outbox == []

    def test_no_email_test(self, demo: None, api_client: APIClient) -> None:
        signed_in(api_client, admin())
        answer = api_client.post(reverse("api-v1:instance-email-test"))
        assert answer.status_code == 403
        assert answer.json()["code"] == "demo"

    def test_no_provider_test(self, demo: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(providers, "discover", lambda issuer: pytest.fail("network"))
        with pytest.raises(mode.DemoRefusedError):
            providers.check(admin(), "https://id.example.com")

    def test_no_sign_in_provider(self, demo: None) -> None:
        OidcProvider.objects.create(
            slug="sso", name="SSO", issuer="https://id.example.com", client_id="x", enabled=True
        )
        assert providers.social_apps() == []

    def test_no_instance_invitation(self, demo: None, api_client: APIClient) -> None:
        signed_in(api_client, admin())
        answer = api_client.post(
            reverse("api-v1:instance-invitation-list"), {"email": "new@example.com"}
        )
        # Refused before the service: no mail server, which the demonstration mode imposes.
        assert answer.status_code == 400
        assert not InstanceInvitation.objects.exists()
        with pytest.raises(mode.DemoRefusedError):
            instance_services.invite(admin(), email="new@example.com", send=lambda *a: None)

    def test_no_home_invitation_by_email(self, demo: None) -> None:
        delivery = home_services.Delivery(send=lambda *a: None)
        with pytest.raises(mode.DemoRefusedError):
            home_services.invite(
                admin(), Home.objects.get(), email="n@example.com", role="member", delivery=delivery
            )
        home_services.invite(
            admin(),
            Home.objects.get(),
            email="n@example.com",
            role="member",
            delivery=home_services.Delivery(),
        )

    def test_a_channel_can_be_added_not_tested(
        self, demo: None, client: Client, settings: Any
    ) -> None:
        settings.HOUSECAIRN_NOTIFICATIONS_ENABLED = True
        channel = notifications.add_channel(member(), name="Phone", url=URL)
        assert Channel.objects.filter(pk=channel.pk).exists()
        signed_in(client, member())
        page = reverse("notifications:channel", kwargs={"channel_id": channel.pk})
        answer = client.post(
            reverse("notifications:test", kwargs={"channel_id": channel.pk}),
            follow=True,
            headers={"referer": f"http://testserver{page}"},
        )
        assert answer.redirect_chain[-1][0].endswith(page)
        assert mode.nothing_sent() in answer.content.decode()

    def test_nothing_is_delivered(self, demo: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(outbound, "_plugin", lambda *a, **k: pytest.fail("network"))
        sealed = outbound.seal(URL)
        assert outbound.deliver(sealed, title="t", body="b") is outbound.Outcome.FAILED

    def test_no_reminder(self, demo: None, monkeypatch: pytest.MonkeyPatch) -> None:
        from housecairn.notifications import reminders

        monkeypatch.setattr(reminders, "_deliver", lambda *a, **k: pytest.fail("sent"))
        assert reminders.dispatch() == 0

    @pytest.fixture
    def device(self, demo: None, settings: Any) -> Device:
        settings.HOUSECAIRN_NOTIFICATIONS_ENABLED = True
        settings.HOUSECAIRN_WEBPUSH_ENABLED = True
        config.invalidate()
        browser = ec.generate_private_key(ec.SECP256R1())
        return devices.subscribe(
            member(),
            name="Phone",
            endpoint="https://fcm.googleapis.com/fcm/send/fixture-not-an-endpoint",
            p256dh=webpush.b64url(webpush.public_bytes(browser.public_key())),
            auth=webpush.b64url(b"0123456789abcdef"),
        )

    def test_a_device_can_be_added_not_tested(
        self, device: Device, client: Client, api_client: APIClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("django_q.tasks.async_task", lambda *a: pytest.fail("queued"))
        signed_in(client, member())
        page = reverse("notifications:device", kwargs={"device_id": device.pk})
        answer = client.post(
            reverse("notifications:device-test", kwargs={"device_id": device.pk}),
            follow=True,
            headers={"referer": f"http://testserver{page}"},
        )
        assert mode.nothing_sent() in answer.content.decode()
        signed_in(api_client, member())
        refused = api_client.post(reverse("api-v1:push-device-test", args=[device.pk]))
        assert refused.status_code == 403
        assert refused.json()["code"] == "demo"

    def test_nothing_is_pushed(self, device: Device, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(webpush, "post", lambda *a, **k: pytest.fail("network"))
        assert devices.send(device, title="t", body="b", path="/") is False
        assert devices.send_test(str(device.pk)) is False

    def test_no_link_preview(self, demo: None) -> None:
        assert config.get_setting("link_preview_enabled") is False


class TestEachRefusalIsTested:
    """One test for each refusal that no other test pins: it falls when its check is removed."""

    def provider(self) -> OidcProvider:
        return OidcProvider.objects.create(
            slug="sso", name="SSO", issuer="https://id.example.com", client_id="x", enabled=True
        )

    def test_a_provider_is_not_changed(self, demo: None) -> None:
        provider = self.provider()
        with pytest.raises(mode.DemoRefusedError):
            providers.update(admin(), provider, {"name": "Defaced"})
        provider.refresh_from_db()
        assert provider.name == "SSO"

    def test_a_provider_is_not_deleted(self, demo: None) -> None:
        provider = self.provider()
        with pytest.raises(mode.DemoRefusedError):
            providers.delete(admin(), provider)
        assert OidcProvider.objects.filter(pk=provider.pk).exists()

    def test_an_instance_invitation_is_not_sent_again(self, demo: None) -> None:
        now = timezone.now()
        invitation = InstanceInvitation.objects.create(
            email="new@example.com",
            invited_by=admin(),
            digest="0" * 64,
            expires_at=now + datetime.timedelta(days=1),
            sent_at=now,
        )
        with pytest.raises(mode.DemoRefusedError):
            instance_services.resend(admin(), invitation, send=lambda *a: pytest.fail("sent"))
        invitation.refresh_from_db()
        assert invitation.digest == "0" * 64

    def test_a_home_invitation_is_not_sent_again_by_email(self, demo: None) -> None:
        invitation, _link = home_services.invite(
            admin(),
            Home.objects.get(),
            email="n@example.com",
            role="member",
            delivery=home_services.Delivery(),
        )
        digest = invitation.digest
        with pytest.raises(mode.DemoRefusedError):
            home_services.resend_invitation(
                admin(),
                invitation,
                delivery=home_services.Delivery(send=lambda *a: pytest.fail("sent")),
            )
        invitation.refresh_from_db()
        assert invitation.digest == digest
        # By link, nothing leaves the server: allowed.
        home_services.resend_invitation(admin(), invitation, delivery=home_services.Delivery())

    def test_a_document_over_four_megabytes_is_refused(
        self, demo: None, settings: Any
    ) -> None:
        archive_bytes = padded_archive(Home.objects.get(), mode.DOCUMENT_MAX_BYTES + 1)
        with pytest.raises(restore.ArchiveRefusedError, match="too large"):
            restore.read_archive(io.BytesIO(archive_bytes))
        settings.HOUSECAIRN_DEMO = False
        restore.read_archive(io.BytesIO(archive_bytes))

    def test_no_linked_identity(self, demo: None) -> None:
        from allauth.socialaccount.models import SocialAccount

        for user in (admin(), member()):
            with pytest.raises(mode.DemoRefusedError), transaction.atomic():
                SocialAccount.objects.create(user=user, provider="sso", uid=f"uid-{user.pk}")
        with mode.reset_context():
            linked = SocialAccount.objects.create(user=admin(), provider="sso", uid="kept")
        with pytest.raises(mode.DemoRefusedError), transaction.atomic():
            linked.delete()
        assert SocialAccount.objects.filter(pk=linked.pk).exists()

    def test_a_due_reminder_is_not_sent(
        self, demo: None, settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from housecairn.notifications import reminders
        from housecairn.tasks import services as task_services

        settings.HOUSECAIRN_NOTIFICATIONS_ENABLED = True
        config.invalidate()
        notifications.add_channel(member(), name="Phone", url=URL)
        task_services.create_task(
            member(), Home.objects.get(), title="Change the filter", due_on=task_services.today()
        )
        sent: list[str] = []
        monkeypatch.setattr(
            reminders.outbound, "send", lambda sealed, *, title, body: sent.append(title) or True
        )
        assert reminders.dispatch() == 0
        assert sent == []
        # The same reminder is due: off, the very same call sends it.
        settings.HOUSECAIRN_DEMO = False
        assert reminders.dispatch() >= 1
        assert sent


class TestAccounts:
    def test_no_password_change(self, demo: None, client: Client) -> None:
        signed_in(client, member())
        answer = client.post(
            reverse("account_change_password"),
            {
                "oldpassword": mode.PASSWORD,
                "password1": "Taken-Over-1234",
                "password2": "Taken-Over-1234",
            },
            follow=True,
        )
        assert "demonstration account" in answer.content.decode()
        assert member().check_password(mode.PASSWORD)

    def test_no_new_address(self, demo: None, client: Client) -> None:
        signed_in(client, member())
        client.post(reverse("account_email"), {"action_add": "", "email": "mine@example.org"})
        assert not EmailAddress.objects.filter(email="mine@example.org").exists()

    def test_no_address_change(self, demo: None) -> None:
        user = member()
        user.email = "mine@example.org"
        with pytest.raises(mode.DemoRefusedError):
            user.save()

    def test_no_admin_rights_change(self, demo: None) -> None:
        user = member()
        user.is_staff = user.is_superuser = True
        with pytest.raises(mode.DemoRefusedError):
            user.save()

    def test_a_display_name_can_change(self, demo: None) -> None:
        user = member()
        user.display_name = "Someone"
        user.save()

    def test_a_rehash_of_the_same_password_is_allowed(self, demo: None) -> None:
        user = member()
        user.set_password(mode.PASSWORD)
        user.save()

    def test_no_second_factor(self, demo: None) -> None:
        from allauth.mfa.models import Authenticator

        with pytest.raises(mode.DemoRefusedError):
            Authenticator.objects.create(user=admin(), type=Authenticator.Type.TOTP, data={})

    def test_no_deletion_on_the_screen(self, demo: None, client: Client) -> None:
        signed_in(client, member())
        client.post(
            reverse("account_delete"), {"password": mode.PASSWORD, "confirm_email": mode.USER_EMAIL}
        )
        assert User.objects.filter(email=mode.USER_EMAIL).exists()

    def test_no_deletion_by_the_api(self, demo: None, api_client: APIClient) -> None:
        signed_in(api_client, member())
        answer = api_client.post(
            reverse("api-v1:account-delete"),
            {"password": mode.PASSWORD, "confirm_email": mode.USER_EMAIL},
            format="json",
        )
        assert answer.status_code == 403
        assert User.objects.filter(email=mode.USER_EMAIL).exists()

    def test_no_deletion_by_the_admin(self, demo: None) -> None:
        with pytest.raises(mode.DemoRefusedError):
            account_services.delete_account(member(), by_admin=admin())
        with pytest.raises(mode.DemoRefusedError):
            account_services.delete_account(member())
        # Refused inside the erasure's transaction: nothing of the accounts went.
        assert Membership.objects.filter(user__email__in=mode.ACCOUNTS).count() == 2
        with pytest.raises(mode.DemoRefusedError), transaction.atomic():
            member().delete()
        assert User.objects.filter(email__in=mode.ACCOUNTS).count() == 2

    def test_no_account_creation(self, demo: None, make_user: Any) -> None:
        with pytest.raises(mode.DemoRefusedError):
            make_user("new@example.org")

    def test_signup_is_closed(self, demo: None, client: Client) -> None:
        assert account_services.signup_is_open() is False
        client.post(
            "/accounts/signup/",
            {
                "email": "new@example.org",
                "password1": "A-long-pass-123",
                "password2": "A-long-pass-123",
            },
        )
        assert not User.objects.filter(email="new@example.org").exists()

    def test_setup_screen_is_closed(self, demo: None, client: Client) -> None:
        assert setup.screen_enabled() is False
        assert client.get(reverse("setup")).status_code in (302, 404)


class TestUploads:
    def test_small_limits(self, demo: None) -> None:
        assert config.get_setting("file_max_bytes") == mode.FILE_MAX_BYTES
        assert quotas.limits().bytes == mode.HOME_STORAGE_MB * quotas.MB

    def test_a_total_for_the_instance(
        self, demo: None, monkeypatch: pytest.MonkeyPatch, make_user: Any
    ) -> None:
        homes = [home_services.create_home(member(), name=f"H{i}") for i in range(3)]
        # Each home well within its own quota, all of them together past the total.
        monkeypatch.setattr(mode, "INSTANCE_STORAGE_BYTES", 30 * quotas.MB)
        held = quotas.Usage(bytes=10 * quotas.MB, files=1)
        monkeypatch.setattr(quotas, "usage", lambda home_id: held)
        with pytest.raises(ValidationError) as caught:
            quotas.check(homes[0], size=quotas.MB)
        assert caught.value.code == "quota_demo"


class TestBanner:
    def test_on_every_page(self, demo: None, client: Client) -> None:
        signed_in(client, member())
        page = client.get(reverse("index"), follow=True).content.decode()
        assert "Demonstration instance" in page
        assert "03:00 (Europe/Paris)" in page

    def test_identifiers_on_the_sign_in_screen(self, demo: None, client: Client) -> None:
        page = client.get(reverse("account_login")).content.decode()
        for text in (mode.ADMIN_EMAIL, mode.USER_EMAIL, mode.PASSWORD):
            assert text in page
