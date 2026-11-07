"""Trusted reverse proxies: forwarding headers count from them only (docs/adr/0012)."""

from collections.abc import Iterator

import pytest
from allauth.account.adapter import get_adapter
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory
from django.urls import reverse
from pytest_django.fixtures import Settings as SettingsWrapper

from housecairn.core.proxy import (
    FORWARDING_HEADERS,
    ForwardedHeadersMiddleware,
    TrustedProxies,
    client_address,
    parse_address,
)

# Documentation ranges (RFC 5737): the proxy, a client, an attacker's claim.
PROXY = "192.0.2.10"
CLIENT = "198.51.100.7"
SPOOFED = "203.0.113.66"


def _through_middleware(**meta: str) -> HttpRequest:
    """A request as the views see it, after ForwardedHeadersMiddleware."""
    seen: list[HttpRequest] = []

    def view(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        return HttpResponse()

    ForwardedHeadersMiddleware(view)(RequestFactory().get("/", **meta))  # type: ignore[arg-type]
    return seen[0]


class TestParse:
    def test_default_is_the_loopback(self, settings: SettingsWrapper) -> None:
        assert settings.HOUSECAIRN_FORWARDED_ALLOW_IPS == ["127.0.0.1", "::1"]

    def test_addresses_and_networks(self) -> None:
        trusted = TrustedProxies.parse([" 192.0.2.10 ", "2001:db8::/32", ""])
        assert trusted.trusts(parse_address("192.0.2.10"))
        assert trusted.trusts(parse_address("2001:db8::5"))
        assert not trusted.trusts(parse_address("192.0.2.11"))
        assert not trusted.trusts(None)

    @pytest.mark.parametrize("entry", ["proxy.example.com", "192.0.2.10/24", "300.1.1.1"])
    def test_invalid_entry_fails(self, entry: str) -> None:
        # Host bits in a network are refused, as gunicorn refuses them.
        with pytest.raises(ImproperlyConfigured, match="HOUSECAIRN_FORWARDED_ALLOW_IPS"):
            TrustedProxies.parse([entry])

    def test_ipv4_mapped_address(self) -> None:
        assert str(parse_address("::ffff:192.0.2.10")) == PROXY
        assert str(parse_address("[2001:db8::1]")) == "2001:db8::1"
        assert parse_address("unknown") is None


class TestClientAddress:
    trusted = TrustedProxies.parse([PROXY, "192.0.2.128/25"])

    def test_right_most_untrusted_entry(self) -> None:
        # The client may write anything on the left; the proxy appends the
        # address it saw.
        assert str(client_address(self.trusted, f"{SPOOFED}, {CLIENT}")) == CLIENT

    def test_skips_trusted_hops(self) -> None:
        header = f"{SPOOFED}, {CLIENT}, 192.0.2.130"
        assert str(client_address(self.trusted, header)) == CLIENT

    def test_stops_at_an_unparsable_entry(self) -> None:
        assert str(client_address(self.trusted, f"{CLIENT}, garbage, 192.0.2.130")) == (
            "192.0.2.130"
        )
        assert client_address(self.trusted, "garbage") is None

    def test_any_peer_takes_the_right_most_entry_only(self) -> None:
        assert str(client_address(TrustedProxies.parse(["*"]), f"{SPOOFED}, {CLIENT}")) == CLIENT


class TestMiddlewareWithTheDefault:
    """No proxy configured: only the loopback may forward."""

    def test_spoofed_forwarded_for_is_not_the_client_address(self) -> None:
        request = _through_middleware(REMOTE_ADDR=CLIENT, HTTP_X_FORWARDED_FOR=SPOOFED)
        assert request.META["REMOTE_ADDR"] == CLIENT
        assert "HTTP_X_FORWARDED_FOR" not in request.META
        assert get_adapter(request).get_client_ip(request) == CLIENT

    def test_every_forwarding_header_is_dropped(self) -> None:
        meta = dict.fromkeys(FORWARDING_HEADERS, "x")
        request = _through_middleware(REMOTE_ADDR=CLIENT, **meta)
        assert not set(FORWARDING_HEADERS) & set(request.META)

    def test_loopback_proxy_is_trusted(self) -> None:
        request = _through_middleware(REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR=CLIENT)
        assert request.META["REMOTE_ADDR"] == CLIENT


class TestMiddlewareWithAProxy:
    @pytest.fixture(autouse=True)
    def _proxy(self, settings: SettingsWrapper) -> None:
        settings.HOUSECAIRN_FORWARDED_ALLOW_IPS = [PROXY]

    def test_client_address_from_the_proxy(self) -> None:
        request = _through_middleware(
            REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=f"{SPOOFED}, {CLIENT}"
        )
        assert request.META["REMOTE_ADDR"] == CLIENT
        assert get_adapter(request).get_client_ip(request) == CLIENT

    def test_other_peer_is_not_trusted(self) -> None:
        request = _through_middleware(REMOTE_ADDR=CLIENT, HTTP_X_FORWARDED_FOR=SPOOFED)
        assert request.META["REMOTE_ADDR"] == CLIENT

    def test_proxy_without_forwarded_for(self) -> None:
        assert _through_middleware(REMOTE_ADDR=PROXY).META["REMOTE_ADDR"] == PROXY


class TestHttpsBehindTheProxy:
    """HOUSECAIRN_BEHIND_TLS_PROXY=true: X-Forwarded-Proto counts from the proxy only."""

    @pytest.fixture(autouse=True)
    def _behind_tls_proxy(self, settings: SettingsWrapper) -> None:
        settings.SECURE_SSL_REDIRECT = True
        settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    def test_untrusted_peer_cannot_claim_https(self) -> None:
        response = Client(REMOTE_ADDR=CLIENT).get("/", HTTP_X_FORWARDED_PROTO="https")
        assert response.status_code == 301
        assert response["Location"].startswith("https://")

    def test_trusted_proxy_can(self) -> None:
        response = Client(REMOTE_ADDR="127.0.0.1").get("/", HTTP_X_FORWARDED_PROTO="https")
        assert response.status_code != 301


@pytest.fixture
def empty_cache() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


def _sign_in_attempts(peer: str, count: int) -> list[int]:
    """Failed sign-ins from `peer`, each with a new X-Forwarded-For and e-mail."""
    client = Client(REMOTE_ADDR=peer)
    statuses = []
    for attempt in range(count):
        response = client.post(
            reverse("account_login"),
            {"login": f"nobody{attempt}@example.com", "password": "wrong-password-123"},
            HTTP_X_FORWARDED_FOR=f"203.0.113.{attempt + 1}",
        )
        statuses.append(response.status_code)
    return statuses


@pytest.mark.django_db
@pytest.mark.usefixtures("empty_cache")
def test_login_rate_limit_ignores_spoofed_forwarded_for() -> None:
    """django-allauth allows 30 sign-in attempts a minute per client address.

    A client that is not a trusted proxy claims a new address in each attempt
    (and uses a new e-mail address, so no per-account limit applies): the 31st
    attempt is still refused, the limit counts its real address.
    """
    statuses = _sign_in_attempts(CLIENT, 31)
    assert set(statuses[:30]) == {200}
    assert statuses[30] == 429


@pytest.mark.django_db
@pytest.mark.usefixtures("empty_cache")
def test_login_rate_limit_counts_the_clients_of_a_trusted_proxy() -> None:
    """The same attempts through the trusted proxy are 31 different clients."""
    assert set(_sign_in_attempts("127.0.0.1", 31)) == {200}
