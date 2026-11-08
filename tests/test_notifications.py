"""Notification channels: sealed addresses, outgoing calls, isolation, API (docs/adr/0043)."""

import datetime
import http.server
import json
import logging
import re
import socket
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import requests
from apprise.plugins.discord import NotifyDiscord
from apprise.plugins.gotify import NotifyGotify
from apprise.plugins.telegram import NotifyTelegram
from django.db import connection
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from housecairn.accounts import services as account_services
from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.audit.models import AuditEvent
from housecairn.homes.models import Home
from housecairn.instance import config
from housecairn.notifications import outbound, reminders, services
from housecairn.notifications.models import Channel, Delivery
from housecairn.tasks import services as task_services
from tests.test_instance_settings import recent

pytestmark = pytest.mark.django_db

TOKEN = "123456:N0t-A-Real-B0t-Token-Anywhere"
URL = f"tgram://{TOKEN}/987654"
LIST = "api-v1:notification-channel-list"


@pytest.fixture(autouse=True)
def _on() -> Iterator[None]:
    with override_settings(HOUSECAIRN_NOTIFICATIONS_ENABLED=True):
        yield


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """What reached the Telegram, Gotify and Discord plugins, without any network."""
    calls: list[tuple[str, str, str]] = []

    def fake(self: Any, body: str, title: str = "", **kwargs: Any) -> bool:
        calls.append((type(self).__name__, title, body))
        return True

    for plugin in (NotifyTelegram, NotifyGotify, NotifyDiscord):
        monkeypatch.setattr(plugin, "send", fake)
    return calls


@pytest.fixture
def channel(alice: User) -> Channel:
    return services.add_channel(alice, name="Phone", url=URL)


def spy_refusals(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The addresses the guard refused while sending."""
    refused: list[str] = []
    real = outbound.forbidden_address

    def spy(address: Any) -> bool:
        if real(address):
            refused.append(str(address))
            return True
        return False

    monkeypatch.setattr(outbound, "forbidden_address", spy)
    return refused


def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


class TestAddresses:
    @pytest.mark.parametrize(
        "url",
        [
            "windows://",
            "syslog://",
            "rsyslog://192.0.2.1",
            "mqtt://broker.example.com/topic",
            "dbus://",
            "file:///etc/passwd",
            "https://example.com/hook",
            # Generic webhooks: their URL chooses the method, the headers and the fields.
            "json://hooks.example.com/hook",
            "jsons://hooks.example.com/admin/delete?method=DELETE",
            "xml://hooks.example.com/hook",
            "xmls://hooks.example.com/hook",
            "form://hooks.example.com/hook",
            "forms://hooks.example.com/hook",
            "not an address",
            "",
        ],
    )
    def test_a_scheme_outside_the_list_is_refused(self, alice: User, url: str) -> None:
        with pytest.raises(services.ValidationError) as caught:
            services.add_channel(alice, name="x", url=url)
        assert "url" in caught.value.message_dict
        assert not Channel.objects.exists()

    @pytest.mark.parametrize(
        "url",
        [
            "gotifys://127.0.0.1/token",
            "ntfy://[::1]/topic",
            "ntfy://169.254.169.254/topic",
            "gotify://[::ffff:127.0.0.1]/token",
            "mmost://0.0.0.0/token",
        ],
    )
    def test_an_address_typed_as_is_is_checked(self, alice: User, url: str) -> None:
        with pytest.raises(services.ValidationError, match="does not send to this address"):
            services.add_channel(alice, name="x", url=url)

    @pytest.mark.parametrize(
        "url",
        [
            "discord://12345/abcdef?template=/etc/passwd",
            "mailtos://user:pass@mail.example.com?to=a@example.com&pgppub=/etc/passwd",
        ],
    )
    def test_options_that_read_a_file_are_refused(self, alice: User, url: str) -> None:
        with pytest.raises(services.ValidationError, match="read a file"):
            services.add_channel(alice, name="x", url=url)

    @pytest.mark.parametrize(
        "url",
        [
            "apprises://api.example.com/token?+X-Admin=1",
            "mailtos://user:pass@mail.example.com?to=a@example.com&+Bcc=b@example.com",
            "ntfys://ntfy.example.com/topic?-message=1",
            "discord://12345/abcdef?:content=x",
            "gotifys://gotify.example.com/token?%2BX-Admin=1",
        ],
    )
    def test_options_that_add_headers_or_fields_are_refused(self, alice: User, url: str) -> None:
        with pytest.raises(services.ValidationError, match="headers or fields"):
            services.add_channel(alice, name="x", url=url)

    @pytest.mark.parametrize("scheme", ["json", "jsons", "xml", "xmls", "form", "forms"])
    def test_a_stored_webhook_channel_is_not_sent_to(
        self, monkeypatch: pytest.MonkeyPatch, scheme: str
    ) -> None:
        """A channel saved before its scheme left the list is refused when it is sent to."""
        called: list[str] = []
        monkeypatch.setattr(requests.Session, "request", lambda *a, **k: called.append("x"))
        sealed = outbound.seal(f"{scheme}://hooks.example.com/hook")
        assert outbound.send(sealed, title="t", body="b") is False
        assert called == []

    def test_a_private_network_is_allowed(self, alice: User) -> None:
        added = services.add_channel(alice, name="ntfy", url="ntfy://172.16.5.20/house")
        assert (added.scheme, added.service) == ("ntfy", "ntfy")

    def test_the_address_is_sealed(self, channel: Channel) -> None:
        assert channel.url.startswith("v1:")
        assert TOKEN not in channel.url
        assert (channel.scheme, channel.service) == ("tgram", "Telegram")

    def test_notifications_off_refuse_a_channel_and_a_test(
        self, alice: User, channel: Channel
    ) -> None:
        with override_settings(HOUSECAIRN_NOTIFICATIONS_ENABLED=False):
            with pytest.raises(services.ValidationError, match="turned off"):
                services.add_channel(alice, name="x", url=URL)
            with pytest.raises(services.ValidationError, match="turned off"):
                services.test_channel(alice, channel)


class TestOutgoingCalls:
    """The guard around Apprise: every address resolved while sending is checked."""

    @pytest.mark.parametrize(
        "address",
        ["127.0.0.1", "::1", "169.254.169.254", "fe80::1", "224.0.0.1", "0.0.0.0"],  # noqa: S104
    )
    def test_a_name_resolving_to_a_refused_address_is_not_called(
        self, monkeypatch: pytest.MonkeyPatch, address: str
    ) -> None:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        monkeypatch.setattr(
            outbound,
            "_resolve",
            lambda *a, **k: [(family, socket.SOCK_STREAM, 6, "", (address, 443))],
        )
        connected: list[Any] = []
        monkeypatch.setattr(socket.socket, "connect", lambda self, a: connected.append(a))
        refused = spy_refusals(monkeypatch)
        sealed = outbound.seal("gotifys://hooks.example.com/token")
        assert outbound.send(sealed, title="t", body="b") is False
        assert connected == []
        assert refused == [address]

    def test_the_guard_only_acts_while_sending(self, monkeypatch: pytest.MonkeyPatch) -> None:
        outbound.install()
        assert socket.getaddrinfo("127.0.0.1", 80)
        with outbound.guarded(), pytest.raises(OSError, match="refused"):
            socket.getaddrinfo("127.0.0.1", 80)

    def test_email_goes_through_the_same_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            outbound,
            "_resolve",
            lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 587))],
        )
        refused = spy_refusals(monkeypatch)
        sealed = outbound.seal("mailtos://user:pass@mail.example.com?to=a@example.com")
        assert outbound.send(sealed, title="t", body="b") is False
        assert refused == ["127.0.0.1"]

    def test_no_redirect_is_followed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits: list[str] = []

        class Redirect(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                hits.append(self.path)
                self.send_response(302)
                port = self.server.server_address[1]
                self.send_header("Location", f"http://127.0.0.1:{port}/elsewhere")
                self.end_headers()

            def do_GET(self) -> None:
                hits.append(self.path)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        # Loopback is refused, rightly: let it through for this test only.
        monkeypatch.setattr(outbound, "forbidden_address", lambda address: False)
        try:
            sealed = outbound.seal(f"gotify://127.0.0.1:{server.server_port}/hook/token")
            assert outbound.send(sealed, title="t", body="b") is False
        finally:
            server.shutdown()
        assert hits == ["/hook/message"]
        # Outside the guard, requests follows redirects as before.
        response = requests.Response()
        response.status_code, response.headers["Location"] = 302, "/next"
        assert requests.Session().get_redirect_target(response) == "/next"

    @pytest.fixture
    def slow_server(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
        """A server that answers one byte every tenth of a second: about 20 s in all."""
        stop = threading.Event()

        class Slow(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                answer = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                answer += b"Content-Length: 160\r\n\r\n" + b'{"id": 1}'.ljust(160)
                for byte in answer:
                    if stop.wait(0.1):
                        return
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()

            def log_message(self, *args: Any) -> None:
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        # Loopback is refused, rightly: let it through for this test only.
        monkeypatch.setattr(outbound, "forbidden_address", lambda address: False)
        monkeypatch.setattr(outbound, "SEND_SECONDS", 1.0, raising=False)
        try:
            yield server.server_port
        finally:
            stop.set()
            server.shutdown()
            server.server_close()

    def test_a_slow_server_holds_a_send_for_the_total_delay_only(self, slow_server: int) -> None:
        sealed = outbound.seal(f"gotify://127.0.0.1:{slow_server}/token")
        started = time.monotonic()
        assert outbound.send(sealed, title="t", body="b") is False
        assert time.monotonic() - started < 3

    def test_the_test_button_and_the_reminders_wait_the_total_delay_only(
        self, slow_server: int, alice: User, alice_home: Home
    ) -> None:
        channel = services.add_channel(
            alice, name="Slow", url=f"gotify://127.0.0.1:{slow_server}/token"
        )
        started = time.monotonic()
        assert services.test_channel(alice, channel) is False
        assert time.monotonic() - started < 3
        task_services.create_task(alice, alice_home, title="Filter", due_on=task_services.today())
        started = time.monotonic()
        assert reminders.dispatch(timezone.now() + datetime.timedelta(days=1)) == 1
        assert time.monotonic() - started < 3
        assert Delivery.objects.get().sent is False

    def test_apprise_does_not_retry(self) -> None:
        plugin = outbound._plugin("gotifys://gotify.example.com/token?retry=5&wait=30")
        assert (plugin.retry, plugin.wait) == (0, 0)

    def test_the_asset_has_no_image_address(self) -> None:
        plugin = apprise.Apprise.instantiate("discord://12345/abcdef", asset=outbound._asset())
        assert plugin.image_url(apprise.NotifyType.INFO) is None
        assert plugin.image_url(apprise.NotifyType.INFO, logo=True) is None

    def test_the_image_options_are_off_whatever_the_address_says(self) -> None:
        plugin = outbound._plugin("discord://12345/abcdef?image=yes&footer_logo=yes&avatar=yes")
        assert (plugin.include_image, plugin.footer_logo, plugin.avatar) == (False, False, False)
        for url in (
            "ntfys://ntfy.example.com/t?image=yes",
            "mmosts://chat.example.com/t?image=yes",
        ):
            assert outbound._plugin(url).include_image is False

    @pytest.mark.parametrize(
        "url",
        [
            "ntfys://ntfy.example.com/topic",
            "gotifys://gotify.example.com/token",
            "signals://signal.example.com/+12025550100/+12025550101",
            "matrixs://user:pass@matrix.example.com/!room:example.com",
            "mmosts://chat.example.com/token",
            "apprises://api.example.com/token",
            "tgram://123456789:AAHexampleexampleexampleexampleexa/987654321",
            "discord://12345/abcdef",
            "slack://T1JJ3T3L2/A1BRTD4JD/TIiajkdnlazkcOXrIdevi7FQ/#general",
            "pover://uuuuuuuuuuuuuuuuuuuuuuuuuuuuuu@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ],
    )
    def test_no_remote_image_in_a_message(self, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
        """Apprise links its icons on github.com: the receiving app would load them."""
        payloads: list[str] = []

        def capture(self: Any, method: str, url: str, **kwargs: Any) -> requests.Response:
            payloads.append(json.dumps([kwargs.get("data"), kwargs.get("json")], default=str))
            answer = requests.Response()
            answer.status_code = 200
            answer._content = b'{"ok": true, "id": 1, "access_token": "t", "room_id": "!r:x"}'
            return answer

        monkeypatch.setattr(requests.Session, "request", capture)
        monkeypatch.setattr(outbound, "forbidden_address", lambda address: False)
        outbound.send(outbound.seal(url), title="Fixed", body="Body")
        assert payloads
        for payload in payloads:
            for image in ("githubusercontent", "github.com", ".png", "http"):
                assert image not in payload

    def test_the_title_is_escaped_for_the_format_of_the_channel(
        self, sent: list[tuple[str, str, str]]
    ) -> None:
        body = "<b>Paint</b> *the* [hall](javascript:alert(1)) & co"
        assert outbound.send(outbound.seal(URL), title="Fixed", body=body)
        assert outbound.send(
            outbound.seal("discord://12345/abcdef?format=markdown"), title="F", body=body
        )
        (_, _, html), (_, _, markdown) = sent
        assert "<b>Paint" not in html
        assert "&lt;b&gt;Paint&lt;/b&gt;" in html
        assert "&amp; co" in html
        assert r"\*the\*" in markdown
        assert r"\[hall\]" in markdown


class TestSurfaces:
    def test_no_surface_carries_the_address(
        self,
        client: Client,
        alice: User,
        api_client: APIClient,
        caplog: Any,
        sent: list[tuple[str, str, str]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        signed_in(client, alice)
        api_client.force_authenticate(alice)
        with caplog.at_level(logging.DEBUG):
            added = client.post(reverse("notifications:add"), {"name": "Phone", "url": URL})
            assert added.status_code == 302
            refused = client.post(
                reverse("notifications:add"), {"name": "x", "url": URL + "?template=/etc/x"}
            )
            api_refused = api_client.post(
                reverse(LIST), {"name": "x", "url": URL + "?template=/etc/x"}, format="json"
            )
            created = api_client.post(reverse(LIST), {"name": "API", "url": URL}, format="json")
            channel = Channel.objects.first()
            assert channel is not None
            detail = reverse("api-v1:notification-channel-detail", args=[channel.id])
            page = reverse("notifications:channel", kwargs={"channel_id": channel.id})
            tested = client.post(reverse("notifications:test", kwargs={"channel_id": channel.id}))
            api_tested = api_client.post(
                reverse("api-v1:notification-channel-test", args=[channel.id])
            )
            # A plugin that fails with the address in its exception: still nothing leaks.
            monkeypatch.setattr(
                NotifyTelegram, "send", lambda *a, **k: (_ for _ in ()).throw(ValueError(URL))
            )
            failed = api_client.post(reverse("api-v1:notification-channel-test", args=[channel.id]))
            outputs = [
                refused.text,
                api_refused.text,
                created.text,
                client.get(reverse("notifications:index")).text,
                client.get(page).text,
                client.get(tested.url).text,
                api_tested.text,
                failed.text,
                api_client.get(reverse(LIST)).text,
                api_client.get(detail).text,
                client.get(reverse("notifications:export")).text,
                api_client.get(reverse("api-v1:notification-export")).text,
                api_client.get(reverse("api-schema")).text,
            ]
        assert json.loads(api_tested.text)["ok"] is True
        assert json.loads(failed.text) == {
            "ok": False,
            "detail": str(services.TEST_RESULTS[False]),
        }
        outputs.append(json.dumps(list(AuditEvent.objects.values()), default=str))
        outputs.append(caplog.text)
        with connection.cursor() as cursor:
            for table in connection.introspection.table_names():
                cursor.execute(f'SELECT * FROM "{table}"')  # noqa: S608 - names from Django
                outputs.append(repr(cursor.fetchall()))
        for output in outputs:
            assert TOKEN not in output
            assert "987654" not in output

    def test_the_export_lists_channels_without_their_address(
        self, client: Client, alice: User, channel: Channel
    ) -> None:
        exported = json.loads(signed_in(client, alice).get(reverse("notifications:export")).text)
        assert exported["channels"] == [
            {
                "id": str(channel.id),
                "name": "Phone",
                "scheme": "tgram",
                "service": "Telegram",
                "enabled": True,
                "created_at": channel.created_at.isoformat(),
            }
        ]
        assert exported["preferences"]["days_before"] == 1

    def test_erasing_the_account_erases_channels_and_deliveries(
        self, alice: User, bob: User, channel: Channel
    ) -> None:
        Delivery.objects.create(user=alice, kind="digest", key="2026-06-15")
        services.add_channel(bob, name="Bob", url=URL)
        account_services.delete_account(alice)
        assert list(Channel.objects.values_list("name", flat=True)) == ["Bob"]
        assert not Delivery.objects.exists()


class TestIsolation:
    @pytest.fixture
    def admin(self, make_user: Callable[..., User]) -> User:
        return make_user("admin@example.com", is_staff=True, is_superuser=True)

    @pytest.mark.parametrize("who", ["bob", "admin"])
    def test_someone_else_gets_the_404_of_a_missing_channel(
        self, client: Client, api_client: APIClient, channel: Channel, request: Any, who: str
    ) -> None:
        other = request.getfixturevalue(who)
        signed_in(client, other)
        api_client.force_authenticate(other)
        missing = "00000000-0000-0000-0000-000000000000"
        for channel_id in (channel.id, missing):
            for name in ("channel", "test", "delete"):
                url = reverse(f"notifications:{name}", kwargs={"channel_id": channel_id})
                answer = client.get(url) if name == "channel" else client.post(url)
                assert answer.status_code == 404
            detail = reverse("api-v1:notification-channel-detail", args=[channel_id])
            assert api_client.get(detail).status_code == 404
            assert api_client.patch(detail, {"name": "x"}, format="json").status_code == 404
            assert api_client.delete(detail).status_code == 404
            test = reverse("api-v1:notification-channel-test", args=[channel_id])
            assert api_client.post(test).status_code == 404
        assert json.loads(api_client.get(reverse(LIST)).text) == []
        assert "Phone" not in client.get(reverse("notifications:index")).text
        assert Channel.objects.get().name == "Phone"

    def test_the_administration_site_has_no_channel(
        self, client: Client, admin: User, channel: Channel
    ) -> None:
        signed_in(client, admin)
        page = client.get(reverse("admin:index")).text
        assert "otification" not in page

    @pytest.mark.parametrize(
        ("scopes", "allowed"), [(["read"], False), (["events"], False), (["read", "write"], True)]
    )
    def test_a_token_needs_the_write_scope(
        self,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        channel: Channel,
        scopes: list[str],
        allowed: bool,
    ) -> None:
        _token, raw = token_services.issue_token(alice, name="t", scopes=scopes, homes=[alice_home])
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        answers = [
            api_client.get(reverse(LIST)),
            api_client.post(reverse(LIST), {"name": "x", "url": URL}, format="json"),
            api_client.get(reverse("api-v1:notification-preferences")),
            api_client.get(reverse("api-v1:notification-export")),
        ]
        codes = [a.status_code for a in answers]
        assert codes == ([200, 201, 200, 200] if allowed else [403] * 4)


class TestWebAndApi:
    def test_add_rename_disable_and_delete_on_the_web(
        self, client: Client, alice: User, sent: list[tuple[str, str, str]]
    ) -> None:
        signed_in(client, alice)
        assert (
            client.post(reverse("notifications:add"), {"name": "Phone", "url": URL}).status_code
            == 302
        )
        channel = Channel.objects.get()
        page = reverse("notifications:channel", kwargs={"channel_id": channel.id})
        assert client.post(page, {"name": "Old phone"}).status_code == 302
        channel.refresh_from_db()
        assert (channel.name, channel.enabled) == ("Old phone", False)
        tested = client.post(reverse("notifications:test", kwargs={"channel_id": channel.id}))
        assert "The test message was sent." in client.get(tested.url).text
        assert "HouseCairn test" in sent[0][2]  # Telegram puts the title in the body
        client.post(reverse("notifications:delete", kwargs={"channel_id": channel.id}))
        assert not Channel.objects.exists()

    def test_the_form_never_shows_the_address_back(self, client: Client, alice: User) -> None:
        signed_in(client, alice)
        answer = client.post(reverse("notifications:add"), {"name": "", "url": URL})
        assert answer.status_code == 422
        assert TOKEN not in answer.text

    def test_tests_are_limited(self, alice: User, channel: Channel, sent: list[Any]) -> None:
        for _ in range(services.TESTS_PER_MINUTE):
            assert services.test_channel(alice, channel) is True
        with pytest.raises(services.ValidationError, match="Too many"):
            services.test_channel(alice, channel)

    def test_api_channels_and_preferences(self, api_client: APIClient, alice: User) -> None:
        api_client.force_authenticate(alice)
        created = api_client.post(reverse(LIST), {"name": "Phone", "url": URL}, format="json")
        assert created.status_code == 201
        assert set(created.json()) == {"id", "name", "scheme", "service", "enabled", "created_at"}
        detail = reverse("api-v1:notification-channel-detail", args=[created.json()["id"]])
        assert (
            api_client.patch(detail, {"enabled": False}, format="json").json()["enabled"] is False
        )
        assert api_client.patch(detail, {"url": "ntfy://x/y"}, format="json").status_code == 200
        assert TOKEN in outbound.crypto.decrypt(Channel.objects.get().url)
        prefs = reverse("api-v1:notification-preferences")
        changed = api_client.patch(
            prefs,
            {
                "quiet_start": "22:00",
                "quiet_end": "07:00",
                "digest": True,
                "time_zone": "Europe/Paris",
            },
            format="json",
        )
        assert changed.status_code == 200
        assert changed.json()["quiet_end"] == "07:00:00"
        half = api_client.patch(prefs, {"quiet_start": None}, format="json")
        assert half.status_code == 400
        wrong = api_client.patch(prefs, {"time_zone": "Mars/Olympus"}, format="json")
        assert wrong.status_code == 400
        assert api_client.delete(detail).status_code == 204

    def test_preferences_on_the_web(self, client: Client, alice: User) -> None:
        signed_in(client, alice)
        url = reverse("notifications:preferences")
        fields = {"days_before": 2, "send_at": "07:30", "language": "fr", "time_zone": ""}
        half = client.post(url, {**fields, "quiet_start": "22:00"})
        assert half.status_code == 422
        assert not services.Preference.objects.exists()
        saved = client.post(url, {**fields, "quiet_start": "22:00", "quiet_end": "07:00"})
        assert saved.status_code == 302
        prefs = services.preferences_of(alice)
        assert (prefs.days_before, str(prefs.quiet_end), prefs.language) == (2, "07:00:00", "fr")

    def test_the_settings_screen_locks_a_variable(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        admin = make_user("admin@example.com", is_staff=True, is_superuser=True)
        recent(client, admin)
        with override_settings(HOUSECAIRN_ENV_LOCKED=frozenset({"notifications_enabled"})):
            assert config.is_locked("notifications_enabled")
            page = client.get(reverse("instance:settings")).text
        tag = re.search(r'<input[^>]*id="locked-notifications_enabled"[^>]*>', page)
        assert tag is not None
        assert "disabled" in tag.group(0)
        assert "checked" in tag.group(0)
        assert 'name="notifications_interval"' in page
        assert config.get_setting("notifications_enabled") is True
        assert config.get_setting("notifications_interval") == 5

    def test_the_more_page_links_to_notifications(self, client: Client, alice: User) -> None:
        page = signed_in(client, alice).get(reverse("more")).text
        assert re.search(r'href="/me/notifications/"', page)
