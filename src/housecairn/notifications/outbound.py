"""Sending through Apprise, kept narrow (docs/adr/0043).

A channel makes the server call an address that a person typed. Apprise has no hook for
that: each plugin opens its own connections. So:

- only the schemes of `ALLOWED_SCHEMES` are accepted: services reached over HTTP(S) or
  SMTP whose plugin fixes the method, the path and the format of each request; nothing
  that runs a program, reads a local file or opens a raw socket, and no generic webhook
  (`json`, `xml`, `form`), whose URL chooses the method, the headers and the fields;
- a URL whose options make Apprise read a file (a template, a PGP key) is refused, and so
  is one whose options add headers or fields to the request (`+name`, `-name`, `:name`);
- while a message is sent, every name resolved in that thread is checked, and the
  connection can only go to the addresses that were checked: loopback, link-local (cloud
  metadata), multicast, unspecified and reserved addresses are refused, as for the test
  of an identity provider (docs/adr/0041); no HTTP redirect is followed;
- certificates are verified and every connection waits five seconds at most;
- Apprise and urllib3 do not log: their messages carry the URLs, hence the secrets.

Nothing outside this module decrypts a channel's address.
"""

import contextlib
import contextvars
import ipaddress
import logging
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import apprise
import requests
from apprise import AppriseAsset, AppriseAttachment, NotifyFormat
from apprise.utils.parse import parse_qsd

from housecairn.instance import crypto
from housecairn.instance.providers import _forbidden_address as forbidden_address

logger = logging.getLogger("housecairn.notifications")

# Services reached over HTTP(S) or SMTP, each in its plain and its TLS form, whose plugin
# fixes the method, the path and the format of every request (docs/adr/0043 lists them).
ALLOWED_SCHEMES = frozenset(
    {
        "ntfy", "ntfys", "gotify", "gotifys", "tgram", "signal", "signals", "matrix",
        "matrixs", "mailto", "mailtos", "discord", "slack", "pover", "apprise", "apprises",
        "mmost", "mmosts",
    }
)  # fmt: skip
# Query options that Apprise turns into extra headers (+), removed fields (-) or added
# fields (:) of the request.
EXTRA_PREFIXES = ("qsd+", "qsd-", "qsd:")
TIMEOUT_SECONDS = 5.0
MAX_URL_LENGTH = 2000


class RefusedError(ValueError):
    """The address is not one the instance sends to; the message says why, without it."""


@dataclass(frozen=True)
class Parsed:
    scheme: str
    service: str


class _Guard:
    """What a send in progress knows; shared with the threads Apprise starts for it."""

    blocked = False


# A context variable, not a thread local: Apprise runs a plugin in its own thread pool, and
# copies the context into it (contextvars.copy_context), so the guard follows the send.
_guard: contextvars.ContextVar[_Guard | None] = contextvars.ContextVar("guard", default=None)
_resolve = socket.getaddrinfo


def _guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
    infos = _resolve(host, port, *args, **kwargs)
    guard = _guard.get()
    if guard is not None:
        for info in infos:
            address = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
            if forbidden_address(address):
                guard.blocked = True
                raise OSError("address refused by the instance")
    return infos


_original_redirect_target = requests.Session.get_redirect_target


def _guarded_redirect_target(self: requests.Session, response: requests.Response) -> Any:
    if _guard.get() is not None:
        return None  # the 3xx answer is returned as is: the plugin counts it as a failure
    return _original_redirect_target(self, response)


def install() -> None:
    """Hook name resolution and redirects once; they act only inside `guarded()`."""
    if socket.getaddrinfo is not _guarded_getaddrinfo:
        socket.getaddrinfo = _guarded_getaddrinfo
    requests.Session.get_redirect_target = _guarded_redirect_target  # type: ignore[method-assign,assignment]
    for name in ("apprise", "urllib3"):
        quiet = logging.getLogger(name)
        quiet.setLevel(logging.CRITICAL + 1)
        quiet.propagate = False


@contextlib.contextmanager
def guarded() -> Iterator[_Guard]:
    install()
    guard = _Guard()
    token = _guard.set(guard)
    try:
        yield guard
    finally:
        _guard.reset(token)


def _asset() -> AppriseAsset:
    # One service at a time, nothing on disk.
    return AppriseAsset(async_mode=False, storage_mode="memory")


def _plugin(url: str) -> Any:
    if not isinstance(url, str) or len(url) > MAX_URL_LENGTH or any(c.isspace() for c in url):
        raise RefusedError("invalid")
    scheme = url.split("://", 1)[0].lower() if "://" in url else ""
    if scheme not in ALLOWED_SCHEMES:
        raise RefusedError("scheme")
    query = parse_qsd(url.split("?", 1)[1]) if "?" in url else {}  # type: ignore[no-untyped-call]
    if any(query.get(extra) for extra in EXTRA_PREFIXES):
        raise RefusedError("fields")
    plugin = apprise.Apprise.instantiate(url, asset=_asset())
    if plugin is None:
        raise RefusedError("invalid")
    protocols = {
        p.lower()
        for attr in ("protocol", "secure_protocol")
        for p in _as_tuple(getattr(plugin, attr, None))
    }
    if scheme not in protocols:
        raise RefusedError("scheme")
    files = [v for v in vars(plugin).values() if isinstance(v, AppriseAttachment) and len(v)]
    if files or getattr(plugin, "pgp_key", None):
        raise RefusedError("options")
    host = getattr(plugin, "host", None)
    if isinstance(host, str) and host:
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            literal = None
        if literal is not None and forbidden_address(literal):
            raise RefusedError("address")
    plugin.verify_certificate = True
    plugin.socket_connect_timeout = TIMEOUT_SECONDS
    plugin.socket_read_timeout = TIMEOUT_SECONDS
    return plugin


def _as_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    return tuple(v for v in value or () if isinstance(v, str))


def parse(url: Any) -> Parsed:
    """Check an address typed by a person; `RefusedError` with a reason code if refused."""
    text = url.strip() if isinstance(url, str) else ""
    plugin = _plugin(text)
    return Parsed(text.split("://", 1)[0].lower(), str(plugin.service_name)[:60])


def seal(url: str) -> str:
    return crypto.encrypt(url.strip())


def send(sealed: str, *, title: str, body: str) -> bool:
    """Send plain text to one channel. True when the service accepted it; never raises.

    Apprise escapes the plain text for the format of the channel (HTML, Markdown), so a
    title typed by a person cannot change the markup of the message.
    """
    try:
        plugin = _plugin(crypto.decrypt(sealed))
        sender = apprise.Apprise(asset=_asset())
        sender.add(plugin)
        with guarded():
            return bool(sender.notify(body=body, title=title, body_format=NotifyFormat.TEXT))
    except Exception as exc:  # a plugin may raise anything; its message may carry the URL
        logger.warning("A notification could not be sent (%s).", type(exc).__name__)
        return False
