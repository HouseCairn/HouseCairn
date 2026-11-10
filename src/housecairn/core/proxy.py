"""Which peers may speak for the client: trusted reverse proxies (docs/adr/0012).

`HOUSECAIRN_FORWARDED_ALLOW_IPS` lists the addresses or networks of the reverse
proxies in front of HouseCairn (default: the loopback, `127.0.0.1,::1`). The
same list is given to gunicorn (`--forwarded-allow-ips`, docs/adr/0015), and
`ForwardedHeadersMiddleware` applies it in Django:

- a request from any other peer loses its forwarding headers
  (`X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host`, `Forwarded`...)
  before anything reads them, so a client that reaches the container directly
  can neither pass for HTTPS nor choose the address it is rate limited under;
- a request from a trusted proxy gets, as `REMOTE_ADDR`, the client address
  that proxy reports in `X-Forwarded-For`: the right-most entry that is not a
  trusted proxy itself. Everything else (django-allauth's rate limits, logs)
  reads `REMOTE_ADDR` only.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse

from housecairn.core.prefix import header_key

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
Address = ipaddress.IPv4Address | ipaddress.IPv6Address

# Request headers, as WSGI names, that only a trusted proxy may set.
FORWARDING_HEADERS = (
    "HTTP_FORWARDED",
    "HTTP_X_FORWARDED_FOR",
    "HTTP_X_FORWARDED_HOST",
    "HTTP_X_FORWARDED_PORT",
    "HTTP_X_FORWARDED_PREFIX",
    "HTTP_X_FORWARDED_PROTO",
    "HTTP_X_FORWARDED_PROTOCOL",
    "HTTP_X_FORWARDED_SSL",
    "HTTP_X_REAL_IP",
)


@dataclass(frozen=True)
class TrustedProxies:
    """Parsed `HOUSECAIRN_FORWARDED_ALLOW_IPS`. `any_peer` stands for `*`."""

    networks: tuple[Network, ...] = ()
    any_peer: bool = False

    @classmethod
    def parse(cls, entries: Iterable[str]) -> TrustedProxies:
        """Addresses and networks as gunicorn reads them (strict: no host bits)."""
        networks: list[Network] = []
        any_peer = False
        for raw in entries:
            entry = raw.strip()
            if not entry:
                continue
            if entry == "*":
                any_peer = True
                continue
            try:
                networks.append(ipaddress.ip_network(entry))
            except ValueError as exc:
                raise ImproperlyConfigured(
                    f"HOUSECAIRN_FORWARDED_ALLOW_IPS: {entry!r} is not an IP address or "
                    "network (for example 192.0.2.10 or 192.0.2.0/24)."
                ) from exc
        return cls(tuple(networks), any_peer)

    def trusts(self, address: Address | None) -> bool:
        if address is None:
            return False
        if self.any_peer:
            return True
        return any(address in network for network in self.networks)


def parse_address(value: str | None) -> Address | None:
    """An IP address, IPv4-mapped IPv6 addresses given as IPv4; None if invalid."""
    if not value:
        return None
    text = value.strip()
    if text.startswith("[") and "]" in text:  # [2001:db8::1]:1234
        text = text[1 : text.index("]")]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def client_address(trusted: TrustedProxies, x_forwarded_for: str) -> Address | None:
    """The client in an `X-Forwarded-For` header received from a trusted proxy.

    Walks the list from the right (the entry added by the proxy that sent the
    request) and stops at the first address that is not a trusted proxy:
    entries further left were written by the client and prove nothing. With
    `*`, only the right-most entry counts. None if there is no usable entry.
    """
    found: Address | None = None
    for entry in reversed(x_forwarded_for.split(",")):
        address = parse_address(entry)
        if address is None:
            break
        found = address
        if trusted.any_peer or not trusted.trusts(address):
            break
    return found


def trusted_proxies() -> TrustedProxies:
    return TrustedProxies.parse(settings.HOUSECAIRN_FORWARDED_ALLOW_IPS)


class ForwardedHeadersMiddleware:
    """First middleware: drop or apply the forwarding headers (module docstring)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.trusted = trusted_proxies()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        meta = request.META
        if not self.trusted.trusts(parse_address(meta.get("REMOTE_ADDR"))):
            for name in FORWARDING_HEADERS:
                meta.pop(name, None)
            # The header that may give the path prefix, when one is named (core.prefix).
            if (prefix_header := header_key()) is not None:
                meta.pop(prefix_header, None)
        elif forwarded_for := meta.get("HTTP_X_FORWARDED_FOR"):
            client = client_address(self.trusted, forwarded_for)
            if client is not None:
                meta["REMOTE_ADDR"] = str(client)
        return self.get_response(request)
