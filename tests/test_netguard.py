"""The guard of outgoing requests: addresses, redirects, rebinding, size and time (docs/adr/0050).

Every refusal is proved with a local server that counts what reaches it: the request must
not have been made. Removing a check makes the matching test fail, which is what they are
for.
"""

import ipaddress
import socket
import threading
import time
from typing import Any

import pytest

from housecairn.core import netguard
from housecairn.core.netguard import Fetched, RefusedError
from tests.netservers import can_bind, endless, open_sockets, serving, trickle

pytestmark = pytest.mark.skipif(not can_bind("127.0.0.2"), reason="needs the 127.0.0.0/8 range")

LOOPBACK = "127.0.0.1"
OTHER = "127.0.0.2"


def only_first_loopback(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """A test policy: 127.0.0.1 is the one server we may call, everything else is refused."""
    return str(address) == LOOPBACK


@pytest.fixture
def local_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netguard, "is_public", only_first_loopback)


def fetch(url: str, **options: Any) -> Fetched:
    options.setdefault("max_bytes", 64 * 1024)
    options.setdefault("seconds", 5.0)
    return netguard.fetch(url, **options)


def refused(url: str, reason: str, **options: Any) -> None:
    with pytest.raises(RefusedError) as caught:
        fetch(url, **options)
    assert caught.value.reason == reason


class TestAddresses:
    @pytest.mark.parametrize(
        "address",
        [
            "8.8.8.8",
            "93.184.216.34",
            "2606:4700:4700::1111",
            "64:ff9b::808:808",  # NAT64 to a public IPv4 address
        ],
    )
    def test_public_addresses_pass(self, address: str) -> None:
        assert netguard.is_public(ipaddress.ip_address(address))

    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "127.1.2.3",
            "0.0.0.0",  # noqa: S104 - the address that is refused
            0x0A000001,  # private network, 10/8
            0xAC100504,  # private network, 172.16/12
            0xC0A8010A,  # private network, 192.168/16
            "100.64.0.1",  # shared address space
            "100.100.100.200",  # Alibaba metadata
            "169.254.169.254",  # AWS, Azure, GCP metadata
            "192.0.0.192",  # Oracle metadata
            "224.0.0.1",
            "240.0.0.1",
            "::1",
            "::",
            "fe80::1",
            "fd00::1",
            "fd00:ec2::254",  # AWS metadata in IPv6
            "::ffff:127.0.0.1",
            "::ffff:a00:1",  # mapped private network, 10/8
            "::ffff:169.254.169.254",
            "64:ff9b::7f00:1",  # NAT64 to the loopback
            "64:ff9b::a9fe:a9fe",  # NAT64 to the metadata service
            "64:ff9b::a00:1",  # NAT64 to a private network, 10/8
            "2002:c0a8:101::",  # 6to4 to a private network, 192.168/16
            "2002:7f00:1::",  # 6to4 to the loopback
            "ff02::1",
        ],
    )
    def test_everything_else_is_refused(self, address: str | int) -> None:
        assert not netguard.is_public(ipaddress.ip_address(address))

    def test_the_rule_of_notifications_still_allows_private_networks(self) -> None:
        assert not netguard.forbidden_address(ipaddress.ip_address(0xC0A8010A))
        assert netguard.forbidden_address(ipaddress.ip_address("127.0.0.1"))
        assert netguard.forbidden_address(ipaddress.ip_address("::ffff:127.0.0.1"))

    def test_a_server_on_the_loopback_is_never_called(self) -> None:
        with serving() as server:
            server.serve("/", 200, b"hello")
            refused(server.url(), "address")
            assert server.connections == 0

    def test_a_mapped_loopback_address_is_never_called(self) -> None:
        with serving() as server:
            server.serve("/", 200, b"hello")
            refused(f"http://[::ffff:127.0.0.1]:{server.port}/", "address")
            assert server.connections == 0

    def test_the_metadata_service_is_never_called(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def connected(self: object) -> None:
            raise AssertionError("a connection was made")

        monkeypatch.setattr(netguard._Pinned, "connect", connected)
        refused("http://169.254.169.254/latest/meta-data/", "address")
        monkeypatch.setattr(
            netguard,
            "_resolve",
            lambda host, port, **kw: [(socket.AF_INET, 1, 6, "", ("169.254.169.254", port))],
        )
        refused("http://metadata.example.com/", "address")

    def test_one_forbidden_address_among_the_answers_refuses_the_name(
        self, monkeypatch: pytest.MonkeyPatch, local_policy: None
    ) -> None:
        with serving() as server:
            server.serve("/", 200, b"hello")
            monkeypatch.setattr(
                netguard,
                "_resolve",
                lambda host, port, **kw: [
                    (socket.AF_INET, 1, 6, "", (LOOPBACK, port)),
                    (socket.AF_INET, 1, 6, "", (OTHER, port)),
                ],
            )
            refused(f"http://mixed.example.com:{server.port}/", "address")
            assert server.connections == 0

    def test_a_name_that_does_not_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def unresolved(host: str, port: int, **kw: Any) -> Any:
            raise socket.gaierror("no such name")

        monkeypatch.setattr(netguard, "_resolve", unresolved)
        refused("http://nowhere.example.com/", "unresolved")


class TestSchemes:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/x",
            "gopher://example.com/",
            "data:text/html,hello",
            "javascript:alert(1)",
            "//example.com/x",
            "example.com/x",
            "",
        ],
    )
    def test_only_http_and_https(self, url: str) -> None:
        refused(url, "scheme")

    def test_no_credentials_in_the_address(self) -> None:
        refused("http://user:secret@example.com/", "credentials")
        refused("http://user@example.com/", "credentials")


class TestRedirects:
    def test_each_hop_is_checked_again(self, local_policy: None) -> None:
        with serving(LOOPBACK) as first, serving(OTHER) as second:
            second.serve("/", 200, b"internal")
            first.redirect("/", second.url("/"))
            refused(first.url(), "address")
            assert first.hits == 1
            assert second.connections == 0

    def test_a_redirect_to_the_metadata_service_is_refused(self, local_policy: None) -> None:
        with serving(LOOPBACK) as first:
            first.redirect("/", "http://169.254.169.254/latest/meta-data/")
            refused(first.url(), "address")

    def test_a_redirect_to_a_file_is_refused(self, local_policy: None) -> None:
        with serving(LOOPBACK) as first:
            first.redirect("/", "file:///etc/passwd")
            refused(first.url(), "scheme")

    def test_a_redirect_to_an_allowed_address_is_followed(self, local_policy: None) -> None:
        with serving(LOOPBACK) as server:
            server.redirect("/a", "/b", 301)
            server.redirect("/b", server.url("/c"), 307)
            server.serve("/c", 200, b"arrived")
            found = fetch(server.url("/a"))
            assert found.body == b"arrived"
            assert found.url == server.url("/c")

    def test_three_redirects_at_most(self, local_policy: None) -> None:
        with serving(LOOPBACK) as server:
            for number in range(5):
                server.redirect(f"/{number}", f"/{number + 1}")
            server.serve("/5", 200, b"end")
            assert fetch(server.url("/2")).body == b"end"  # /2 -> /3 -> /4 -> /5: three hops
            refused(server.url("/1"), "redirects")  # four hops
            server.redirect("/loop", "/loop")
            refused(server.url("/loop"), "redirects")

    def test_a_redirect_without_a_target_is_a_failure(self, local_policy: None) -> None:
        with serving(LOOPBACK) as server:
            server.routes["/"] = lambda h: (302, {}, b"")
            refused(server.url(), "status")


class TestRebinding:
    def test_the_connection_goes_to_the_address_that_was_checked(
        self, monkeypatch: pytest.MonkeyPatch, local_policy: None
    ) -> None:
        """The name answers a safe address first and a forbidden one afterwards."""
        with serving(LOOPBACK) as safe, serving(OTHER, safe.port) as trap:
            safe.serve("/", 200, b"safe")
            trap.serve("/", 200, b"trap")
            answers = iter([LOOPBACK, OTHER, OTHER, OTHER])
            calls: list[str] = []

            def resolve(host: str, port: int, **kw: Any) -> Any:
                calls.append(host)
                return [(socket.AF_INET, 1, 6, "", (next(answers), port))]

            monkeypatch.setattr(netguard, "_resolve", resolve)
            found = fetch(f"http://rebind.example.com:{safe.port}/")
            assert found.body == b"safe"
            assert calls == ["rebind.example.com"]  # resolved once, not asked again
            assert trap.connections == 0


class TestSize:
    def test_a_huge_page_is_cut_at_the_limit(self, local_policy: None) -> None:
        with serving(LOOPBACK) as server:
            server.routes["/"] = endless
            found = fetch(server.url(), max_bytes=100_000, truncate=True)
            assert found.truncated
            assert len(found.body) == 100_000
            assert server.wait_idle()
            assert server.bytes_sent < 10_000_000  # a few buffers, not the 40 MB on offer

    def test_a_huge_file_is_refused(self, local_policy: None) -> None:
        with serving(LOOPBACK) as server:
            server.routes["/"] = endless
            refused(server.url(), "too_large", max_bytes=100_000)
            assert server.wait_idle()
            assert server.bytes_sent < 10_000_000

    def test_a_declared_size_over_the_limit_is_refused_before_reading(
        self, local_policy: None
    ) -> None:
        release = threading.Event()

        def announce_and_wait(handler: Any) -> None:
            # The size is announced, then nothing comes: only a client that reads the body
            # waits for it, one that trusts the announcement answers at once.
            handler.wfile.write(b"HTTP/1.0 200 OK\r\nContent-Length: 50000000\r\n\r\n")
            handler.wfile.flush()
            release.wait(10)

        with serving(LOOPBACK) as server:
            server.routes["/"] = announce_and_wait
            started = time.monotonic()
            try:
                refused(server.url(), "too_large", max_bytes=100_000, seconds=5.0)
                assert time.monotonic() - started < 3.0
            finally:
                release.set()

    def test_a_page_within_the_limit_is_returned_whole(self, local_policy: None) -> None:
        with serving(LOOPBACK) as server:
            server.serve("/", 200, b"<html>ok</html>", "text/html; charset=iso-8859-1")
            found = fetch(server.url())
            assert (found.body, found.content_type, found.charset, found.truncated) == (
                b"<html>ok</html>",
                "text/html",
                "iso-8859-1",
                False,
            )

    def test_an_error_status_is_a_failure(self, local_policy: None) -> None:
        with serving(LOOPBACK) as server:
            server.serve("/", 500, b"oops")
            refused(server.url(), "status")
            refused(server.url("/missing"), "status")


class TestTime:
    def test_a_page_that_trickles_is_given_up_on_and_nothing_stays_open(
        self, local_policy: None
    ) -> None:
        threads = threading.active_count()
        with serving(LOOPBACK) as server:
            server.routes["/"] = trickle
            started = time.monotonic()
            refused(server.url(), "timeout", seconds=1.0)
            assert time.monotonic() - started < 3.0
            assert server.wait_idle(), "the client left a connection open"
        assert threading.active_count() <= threads
        assert not [t for t in threading.enumerate() if isinstance(t, threading.Timer)]

    def test_a_header_block_that_trickles_is_given_up_on(self, local_policy: None) -> None:
        with serving(LOOPBACK) as server:
            server.routes["/"] = lambda h: trickle(h, headers_first=True)
            outcome: list[BaseException | None] = []

            def attempt() -> None:
                try:
                    fetch(server.url(), seconds=1.0)
                except BaseException as exc:
                    outcome.append(exc)
                else:
                    outcome.append(None)

            # A guard of the test's own: without the watchdog of `fetch` the read never
            # ends, and the test must fail instead of hanging the suite.
            started = time.monotonic()
            worker = threading.Thread(target=attempt, daemon=True)
            worker.start()
            worker.join(timeout=6.0)
            assert not worker.is_alive(), "the header block was never given up on"
            assert time.monotonic() - started < 3.0
            assert isinstance(outcome[0], RefusedError)
            assert outcome[0].reason == "timeout"
            assert server.wait_idle()

    def test_a_server_that_never_answers(self, local_policy: None) -> None:
        release = threading.Event()
        with serving(LOOPBACK) as server:
            server.routes["/"] = lambda h: release.wait(10) and None
            started = time.monotonic()
            try:
                refused(server.url(), "timeout", seconds=1.0)
                assert time.monotonic() - started < 3.0
            finally:
                release.set()
            assert server.wait_idle()

    def test_the_deadline_covers_the_redirects_together(self, local_policy: None) -> None:
        with serving(LOOPBACK) as server:
            server.redirect("/a", "/b")
            server.routes["/b"] = trickle
            started = time.monotonic()
            refused(server.url("/a"), "timeout", seconds=1.0)
            assert time.monotonic() - started < 3.0

    def test_sockets_do_not_pile_up(self, local_policy: None) -> None:
        with serving(LOOPBACK) as server:
            server.serve("/", 200, b"ok")
            fetch(server.url())
            assert server.wait_idle()
            before = open_sockets()
            for _ in range(20):
                fetch(server.url())
                refused(server.url("/missing"), "status")
            assert server.wait_idle()
            assert open_sockets() <= before


def test_a_server_is_a_server() -> None:
    """Sanity of the helper: the tests above would pass for the wrong reason otherwise."""
    with serving() as server:
        server.serve("/", 200, b"hello")
        with socket.create_connection((LOOPBACK, server.port), timeout=2) as client:
            client.sendall(b"GET / HTTP/1.0\r\n\r\n")
            received = b""
            while chunk := client.recv(4096):
                received += chunk
            assert received.endswith(b"hello")
        assert server.hits == 1


class TestTls:
    def test_the_secure_connection_refuses_old_protocols(
        self, monkeypatch: pytest.MonkeyPatch, local_policy: None
    ) -> None:
        import ssl

        seen: list[Any] = []

        class Context:
            minimum_version = ssl.TLSVersion.TLSv1

            def wrap_socket(self, sock: socket.socket, server_hostname: str) -> socket.socket:
                seen.append((self.minimum_version, server_hostname))
                return sock

        monkeypatch.setattr(netguard.ssl, "create_default_context", lambda: Context())
        with serving(LOOPBACK) as server:
            server.serve("/", 200, b"ok")
            monkeypatch.setattr(
                netguard,
                "_resolve",
                lambda host, port, **kw: [(socket.AF_INET, 1, 6, "", (LOOPBACK, port))],
            )
            # The server speaks plain HTTP, so the fake context hands the socket back as is.
            found = fetch(f"https://secure.example.com:{server.port}/")
        assert found.body == b"ok"
        assert seen == [(ssl.TLSVersion.TLSv1_2, "secure.example.com")]
