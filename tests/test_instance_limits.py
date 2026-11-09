"""Rate limits, quotas per home, language, time zone and name of the instance (ADR 0042)."""

import datetime
import json
import time
import zoneinfo
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from allauth.account import app_settings as allauth_settings
from allauth.account.internal.userkit import user_id_to_str
from django.core import mail
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes import quotas
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.instance import config, registry
from housecairn.instance import settings_services as svc
from housecairn.rooms import services as room_services
from housecairn.rooms.models import Item, Photo, Room
from housecairn.stock.models import Article
from housecairn.tasks import services as task_services
from housecairn.tasks.models import Attachment, Task
from tests.rooms_support import image_bytes, noise_image, upload
from tests.tasks_fixtures import PDF

pytest_plugins = ("tests.tasks_fixtures",)
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]

NEW = [
    key
    for key, s in registry.SETTINGS.items()
    if s.section
    in (registry.Section.INSTANCE, registry.Section.RATE_LIMITS, registry.Section.FILES)
]
NUMBERS = [k for k in NEW if registry.SETTINGS[k].kind is registry.Kind.INT]
EVIL_NAME = '<script>alert("x")</script> & Co'


def recent(client: Client | APIClient, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["account_authentication_methods"] = [{"method": "password", "at": time.time()}]
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


def section_of(key: str) -> str:
    return registry.SETTINGS[key].section.value


# ---------- the pair variable / interface, for every new setting ----------


class TestEverySetting:
    def test_the_defaults_keep_the_former_behaviour(self) -> None:
        assert allauth_settings.RATE_LIMITS["login"] == "30/m/ip"
        assert allauth_settings.RATE_LIMITS["login_failed"] == "10/m/ip,5/300s/key"
        assert allauth_settings.RATE_LIMITS["signup"] == "10/m/ip,60/d/ip"
        assert allauth_settings.RATE_LIMITS["reset_password"] == "20/m/ip,5/m/key"
        for action in ("housecairn_invite", "housecairn_instance_invite"):
            assert allauth_settings.RATE_LIMITS[action] == "10/m/user,50/d/user"
        assert allauth_settings.RATE_LIMITS["housecairn_invitation"] == "30/m/ip"
        assert allauth_settings.RATE_LIMITS["housecairn_settings_test"] == "5/m/user"
        assert allauth_settings.RATE_LIMITS["housecairn_delete_account"] == "5/m/user"
        assert config.get_setting("file_max_bytes") == 10 * 1024 * 1024
        assert config.get_setting("time_zone") == "UTC"
        assert config.get_setting("default_language") == "en"
        assert config.instance_name() == "HouseCairn"

    @pytest.mark.parametrize("key", NUMBERS)
    def test_out_of_bounds_is_refused_everywhere(
        self, key: str, admin_user: User, admin_client: Client, admin_api: APIClient
    ) -> None:
        setting = registry.SETTINGS[key]
        assert setting.minimum is not None
        assert setting.minimum >= 1
        assert setting.maximum is not None
        for value in (0, setting.minimum - 1, setting.maximum + 1, -1):
            with pytest.raises(ValidationError):
                svc.update(admin_user, {key: value})
            page = admin_client.post(
                reverse("instance:settings", kwargs={"section": section_of(key)}),
                {"section": section_of(key), key: value},
            )
            assert page.status_code == 422, (key, value)
            answer = admin_api.patch(reverse("api-v1:instance-settings"), {key: value})
            assert answer.status_code == 400, (key, value)
        assert config.source(key) == "default"
        with pytest.raises(ImproperlyConfigured, match=setting.env):
            registry.read_environment({setting.env: str(setting.maximum + 1)})
        with pytest.raises(ImproperlyConfigured, match=setting.env):
            registry.read_environment({setting.env: "0"})

    @pytest.mark.parametrize("key", NEW)
    def test_a_variable_locks_it_and_the_screen_shows_the_value(
        self, key: str, admin_user: User, admin_client: Client
    ) -> None:
        setting = registry.SETTINGS[key]
        value = {
            registry.Kind.INT: str(setting.maximum),
            registry.Kind.CHOICE: "fr",
            registry.Kind.STR: "Europe/Paris" if key == "time_zone" else "Dupont",
        }[setting.kind]
        read = registry.read_environment({setting.env: value})
        assert key in read.locked
        with override_settings(
            HOUSECAIRN_ENV_LOCKED=frozenset({key}), **{setting.django_name: read.values[key]}
        ):
            assert config.get_setting(key) == read.values[key]
            with pytest.raises(ValidationError, match=setting.env):
                svc.update(admin_user, {key: setting.default})
            page = admin_client.get(
                reverse("instance:settings", kwargs={"section": section_of(key)}),
                HTTP_ACCEPT_LANGUAGE="en",
            ).text
            assert f'id="locked-{key}"' in page
            assert f'name="{key}"' not in page
            assert f"<code>{setting.env}</code>" in page
            assert f"Value in force: {read.values[key]}" in page

    @pytest.mark.parametrize("key", NUMBERS)
    def test_set_then_restore_the_default(self, key: str, admin_user: User) -> None:
        setting = registry.SETTINGS[key]
        value = setting.default + 1  # within its bounds and the rules between settings
        svc.update(admin_user, {key: value})
        assert (config.get_setting(key), config.source(key)) == (value, "database")
        svc.reset(admin_user, key)
        assert (config.get_setting(key), config.source(key)) == (setting.default, "default")


# ---------- rate limits ----------


class TestRateLimits:
    def test_a_change_reaches_allauth_without_a_restart(self, admin_user: User) -> None:
        svc.update(admin_user, {"ratelimit_login": 7, "ratelimit_login_failures": 3})
        assert allauth_settings.RATE_LIMITS["login"] == "7/m/ip"
        assert allauth_settings.RATE_LIMITS["login_failed"] == "10/m/ip,3/300s/key"
        svc.reset(admin_user, "ratelimit_login")
        assert allauth_settings.RATE_LIMITS["login"] == "30/m/ip"

    def test_the_new_limit_applies(self, admin_user: User, client: Client) -> None:
        svc.update(admin_user, {"ratelimit_invitation_links": 2})
        address = reverse("invitation", kwargs={"token": "unknown"})
        assert [client.get(address).status_code for _ in range(3)] == [404, 404, 429]

    def test_a_day_cannot_allow_fewer_than_a_minute(self, admin_user: User) -> None:
        with pytest.raises(ValidationError, match="fewer than a minute") as raised:
            svc.update(admin_user, {"ratelimit_signup_day": 5})
        assert list(raised.value.message_dict) == ["ratelimit_signup_day"]
        with pytest.raises(ValidationError, match="fewer than a minute"):
            svc.update(admin_user, {"ratelimit_invitations": 60})
        svc.update(admin_user, {"ratelimit_invitations": 60, "ratelimit_invitations_day": 60})
        assert config.get_setting("ratelimit_invitations") == 60
        # Restoring the default of the day would leave 50 a day for 60 a minute.
        with pytest.raises(ValidationError, match="fewer than a minute"):
            svc.reset(admin_user, "ratelimit_invitations_day")


# ---------- quotas ----------


@pytest.fixture
def full(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Set the quotas; `bytes` small enough for one test image."""

    def set_limits(*, files: int = 1000, size: int = 10**9) -> None:
        monkeypatch.setattr(quotas, "limits", lambda: quotas.Limits(bytes=size, files=files))

    return set_limits


def api_of(user: User, api_client: APIClient) -> APIClient:
    api_client.force_authenticate(user)
    return api_client


class TestQuotas:
    """Every way to store a file: photo of a room or an item, attachment, label; web, API."""

    def test_the_count_includes_every_app_and_deleted_files(
        self,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        owner_task: Task,
        admin_user: User,
    ) -> None:
        photo = room_services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))
        task_services.add_attachment(alice, owner_task, upload=upload(PDF, "a.pdf"))
        held = quotas.usage(alice_home.id)
        assert held.files == 2  # the thumbnail is not a file of its own
        assert held.bytes >= photo.size_bytes + len(PDF)
        room_services.delete_photo(alice, photo)
        assert quotas.usage(alice_home.id) == held  # deleted, still on disk until purged
        svc.update(admin_user, {"home_max_files": 2})
        with pytest.raises(ValidationError, match="already holds 2 files"):
            room_services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))
        assert Photo.all_objects.filter(home=alice_home).count() == 1

    def test_the_space_quota_names_the_numbers(
        self, alice: User, owner_room: Room, full: Callable[..., None]
    ) -> None:
        full(size=1000)
        with pytest.raises(ValidationError, match="no room left") as raised:
            room_services.add_photo(alice, room=owner_room, upload=upload(noise_image()))
        assert "of 1000" in raised.value.messages[0]
        assert not Photo.all_objects.exists()
        assert quotas.usage(owner_room.home_id).files == 0  # nothing left on disk

    def test_room_and_item_photos_on_the_web(
        self,
        signed_in: Client,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        full: Callable[..., None],
    ) -> None:
        full(files=0)
        for name, kwargs in (
            ("room-photo-add", {"room_id": owner_room.id}),
            ("item-photo-add", {"item_id": owner_item.id}),
        ):
            address = reverse(f"rooms:{name}", kwargs={"home_id": alice_home.id, **kwargs})
            page = signed_in.post(address, {"file": upload(image_bytes()), "category": "general"})
            assert page.status_code == 200, name
            assert "already holds 0 files" in page.text
        assert not Photo.all_objects.exists()

    def test_photos_through_the_api(
        self,
        alice: User,
        api_client: APIClient,
        alice_home: Home,
        owner_room: Room,
        full: Callable[..., None],
    ) -> None:
        full(files=0)
        answer = api_of(alice, api_client).post(
            reverse("api-v1:home-photo-list", kwargs={"home_id": alice_home.id}),
            {"file": upload(image_bytes()), "room": str(owner_room.id)},
            format="multipart",
        )
        assert answer.status_code == 400
        assert "already holds 0 files" in json.dumps(answer.json())

    def test_attachments_on_the_web_one_by_one(
        self,
        signed_in: Client,
        alice_home: Home,
        owner_task: Task,
        admin_user: User,
    ) -> None:
        svc.update(admin_user, {"home_max_files": 1})
        address = reverse(
            "tasks:attachment-add", kwargs={"home_id": alice_home.id, "task_id": owner_task.id}
        )
        page = signed_in.post(
            address, {"uploads": [upload(PDF, "one.pdf"), upload(PDF, "two.pdf")]}
        )
        assert "already holds 1 files" in page.content.decode()
        assert Attachment.objects.filter(task=owner_task).count() == 1

    def test_attachments_through_the_api(
        self,
        alice: User,
        api_client: APIClient,
        alice_home: Home,
        owner_task: Task,
        full: Callable[..., None],
    ) -> None:
        full(size=10)
        answer = api_of(alice, api_client).post(
            reverse("api-v1:home-attachment-list", kwargs={"home_id": alice_home.id}),
            {"task": str(owner_task.id), "file": upload(PDF, "a.pdf")},
            format="multipart",
        )
        assert answer.status_code == 400
        assert "no room left" in json.dumps(answer.json())
        assert not Attachment.all_objects.exists()

    def test_stock_labels_on_the_web_and_the_api(
        self,
        alice: User,
        signed_in: Client,
        api_client: APIClient,
        alice_home: Home,
        full: Callable[..., None],
    ) -> None:
        full(files=0)
        page = signed_in.post(
            reverse("stock:create", kwargs={"home_id": alice_home.id}),
            {"name": "Anode", "label": upload(image_bytes(), "label.jpg")},
        )
        assert page.status_code in (200, 422)
        assert "already holds 0 files" in page.text
        answer = api_of(alice, api_client).post(
            reverse("api-v1:home-article-list", kwargs={"home_id": alice_home.id}),
            {"name": "Tin", "label": upload(image_bytes(), "x.jpg")},
            format="multipart",
        )
        assert answer.status_code == 400
        assert "already holds 0 files" in json.dumps(answer.json())
        assert not Article.all_objects.exists()

    def test_replacing_a_label_is_not_a_new_file(
        self, alice: User, alice_home: Home, admin_user: User
    ) -> None:
        from housecairn.stock import services as stock_services

        article = stock_services.create_article(
            alice, alice_home, name="Tin", label=upload(image_bytes())
        )
        svc.update(admin_user, {"home_max_files": 1})
        stock_services.update_article(alice, article, label=upload(image_bytes("PNG"), "x.png"))
        assert quotas.usage(alice_home.id).files == 1

    def test_the_largest_file_is_a_setting(
        self, alice: User, owner_room: Room, admin_user: User
    ) -> None:
        data = noise_image()
        svc.update(admin_user, {"file_max_bytes": 10 * 1024})
        assert len(data) > 10 * 1024
        with pytest.raises(ValidationError, match="too large"):
            room_services.add_photo(alice, room=owner_room, upload=upload(data))


class TestUsageScreen:
    def test_the_administrator_sees_numbers_and_no_content(
        self,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        owner_task: Task,
        admin_client: Client,
        admin_api: APIClient,
    ) -> None:
        alice_home.name = "Secret Manor"
        alice_home.save()
        room_services.add_photo(
            alice, room=owner_room, upload=upload(image_bytes()), caption="Hidden caption"
        )
        task_services.add_attachment(
            alice, owner_task, upload=upload(PDF, "private-deed.pdf"), name="private-deed.pdf"
        )
        page = admin_client.get(reverse("instance:usage")).text
        listing = admin_api.get(reverse("api-v1:instance-usage")).json()
        assert str(alice_home.id) in page
        assert listing["homes"] == [
            {
                "id": str(alice_home.id),
                "bytes": quotas.usage(alice_home.id).bytes,
                "files": 2,
                "percent": 0,
            }
        ]
        assert listing["limits"] == {"bytes": 5120 * 1024 * 1024, "files": 5000}
        shown = page + json.dumps(listing)
        for private in (
            "Secret Manor",
            "Hidden caption",
            "private-deed",
            owner_room.name,
            owner_task.title,
            alice.email,
        ):
            assert private not in shown, private
        assert "Files of the homes" in admin_client.get(reverse("instance:overview")).text

    def test_a_member_and_a_token_get_nothing(
        self, alice: User, alice_home: Home, client: Client, api_client: APIClient, admin_user: User
    ) -> None:
        client.force_login(alice)
        assert client.get(reverse("instance:usage")).status_code == 404
        api_client.force_authenticate(alice)
        assert api_client.get(reverse("api-v1:instance-usage")).status_code == 403
        own = home_services.create_home(admin_user, name="Own")
        _token, raw = token_services.issue_token(
            admin_user, name="t", scopes=["read", "write"], homes=[own]
        )
        other = APIClient()
        other.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert other.get(reverse("api-v1:instance-usage")).status_code == 403


# ---------- language and time zone ----------


class TestLanguage:
    def test_the_default_language_is_for_browsers_that_ask_for_none(
        self, admin_user: User, client: Client
    ) -> None:
        svc.update(admin_user, {"default_language": "fr"})
        assert '<html lang="fr">' in client.get(reverse("account_login")).text
        assert (
            '<html lang="fr">'
            in client.get(reverse("account_login"), HTTP_ACCEPT_LANGUAGE="de-DE,de;q=0.9").text
        )
        # The person's choice wins: the browser, then the language cookie.
        asked = client.get(reverse("account_login"), HTTP_ACCEPT_LANGUAGE="en-GB,en;q=0.9")
        assert '<html lang="en">' in asked.text
        client.cookies["django_language"] = "en"
        assert '<html lang="en">' in client.get(reverse("account_login")).text

    def test_an_unknown_language_is_refused(self, admin_user: User) -> None:
        for value in ("de", "", "<b>", "fr-FR"):
            with pytest.raises(ValidationError):
                svc.update(admin_user, {"default_language": value})
        with pytest.raises(ImproperlyConfigured, match="HOUSECAIRN_DEFAULT_LANGUAGE"):
            registry.read_environment({"HOUSECAIRN_DEFAULT_LANGUAGE": "de"})

    def test_the_languages_are_those_of_django(self, settings: Any) -> None:
        assert tuple(code for code, _name in settings.LANGUAGES) == registry.LANGUAGES

    def test_an_invitation_email_without_a_language_uses_it(
        self, admin_user: User, alice: User, alice_home: Home
    ) -> None:
        from housecairn.homes import emails

        svc.update(admin_user, {"default_language": "fr"})
        invitation, _raw = home_services.invite(
            alice,
            alice_home,
            email="guest@example.com",
            role="member",
            delivery=home_services.Delivery(),
        )
        emails.send_invitation(invitation, "https://example.com/x", language=None)
        assert "invité" in mail.outbox[-1].subject


class TestTimeZone:
    def test_today_and_the_pages_follow_it(self, admin_user: User, client: Client) -> None:
        moment = datetime.datetime(2026, 3, 28, 23, 30, tzinfo=datetime.UTC)
        with mock.patch("django.utils.timezone.now", return_value=moment):
            assert task_services.today() == datetime.date(2026, 3, 28)
            svc.update(admin_user, {"time_zone": "Europe/Paris"})
            assert task_services.today() == datetime.date(2026, 3, 29)
        seen: list[Any] = []

        def capture(request: Any) -> Any:
            from django.http import HttpResponse
            from django.utils import timezone

            seen.append(timezone.get_current_timezone())
            return HttpResponse("ok")

        from housecairn.instance.middleware import InstanceTimeZoneMiddleware

        InstanceTimeZoneMiddleware(capture)(mock.Mock())
        assert seen == [zoneinfo.ZoneInfo("Europe/Paris")]

    @pytest.mark.parametrize("value", ["Mars/Olympus", "europe/paris", "../etc/passwd", "UTC+1"])
    def test_an_unknown_zone_is_refused(self, admin_user: User, value: str) -> None:
        with pytest.raises(ValidationError, match="IANA"):
            svc.update(admin_user, {"time_zone": value})
        with pytest.raises(ImproperlyConfigured, match="TIME_ZONE"):
            registry.read_environment({"TIME_ZONE": value})

    def test_an_unreadable_stored_zone_falls_back_to_utc(self) -> None:
        with mock.patch.object(config, "get_setting", return_value="Nowhere/Land"):
            assert config.instance_zone() == zoneinfo.ZoneInfo("UTC")


# ---------- name of the instance ----------


class TestInstanceName:
    def test_it_is_escaped_in_the_title_the_bar_and_the_manifest(
        self, admin_user: User, client: Client
    ) -> None:
        svc.update(admin_user, {"instance_name": EVIL_NAME})
        page = client.get(reverse("account_login")).text
        assert "<script>alert" not in page
        escaped = "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; Co"
        assert f"· {escaped}</title>" in page
        assert f'<span class="brand-instance">{escaped}</span>' in page
        manifest = client.get(reverse("manifest"))
        assert manifest.json()["name"] == EVIL_NAME
        assert "<script>" not in manifest.content.decode()

    def test_it_is_in_the_emails_escaped_in_html(
        self, admin_user: User, alice: User, alice_home: Home
    ) -> None:
        from housecairn.homes import emails

        svc.update(admin_user, {"instance_name": EVIL_NAME})
        invitation, _raw = home_services.invite(
            alice,
            alice_home,
            email="guest@example.com",
            role="member",
            delivery=home_services.Delivery(),
        )
        emails.send_invitation(invitation, "https://example.com/x", language="en")
        message = mail.outbox[-1]
        assert message.subject == f"{EVIL_NAME}: you are invited to Main house"
        html = message.alternatives[0][0]  # type: ignore[attr-defined]
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_allauth_subjects_start_with_it(self, admin_user: User) -> None:
        from allauth.account.adapter import get_adapter

        svc.update(admin_user, {"instance_name": "Dupont family"})
        assert get_adapter().format_email_subject("Hello") == "Dupont family: Hello"

    @pytest.mark.parametrize(
        "value", ["two\nlines", "x" * 65, "bell\x07", "right\u202eleft", "tab\there"]
    )
    def test_a_name_that_could_break_a_header_or_a_page_is_refused(
        self, admin_user: User, value: str
    ) -> None:
        with pytest.raises(ValidationError):
            svc.update(admin_user, {"instance_name": value})
        with pytest.raises(ImproperlyConfigured, match="HOUSECAIRN_INSTANCE_NAME"):
            registry.read_environment({"HOUSECAIRN_INSTANCE_NAME": value})

    def test_empty_shows_the_product_name(self, admin_user: User, client: Client) -> None:
        svc.update(admin_user, {"instance_name": ""})
        assert config.instance_name() == "HouseCairn"
        assert "brand-instance" not in client.get(reverse("account_login")).text


def test_quota_numbers_need_no_home_name(tmp_path: Path) -> None:
    """`by_home` reads identifiers only: the query names no other column."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as queries:
        quotas.by_home()
    sql = " ".join(q["sql"] for q in queries.captured_queries if "homes_home" in q["sql"])
    assert '"name"' not in sql
