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
  connection can only go to the addresses that were checked: loopback, link-local,
  multicast, unspecified and reserved addresses are refused, as for the test of an
  identity provider (docs/adr/0041), and so are the metadata services of cloud providers
  (`METADATA_ADDRESSES`), private networks being allowed; no HTTP redirect is followed;
- certificates are verified; each wait of a connection lasts five seconds at most, and a
  send to one channel gives up after `SEND_SECONDS` in all, however slowly the server
  answers; then every socket the send opened is shut down, so the thread of the plugin
  ends too, and it cannot open another; Apprise does not retry;
- Apprise and urllib3 do not log: their messages carry the URLs, hence the secrets.

Nothing outside this module decrypts a channel's address.
"""

import contextlib
import contextvars
import ipaddress
import logging
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import apprise
import requests
from apprise import AppriseAsset, AppriseAttachment, NotifyFormat
from apprise.plugins.matrix import NotifyMatrix
from apprise.utils.parse import parse_qsd

from housecairn.instance import crypto
from housecairn.instance.providers import _embedded_ipv4
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
# Each wait of a socket (connect, read), and the whole send to one channel.
TIMEOUT_SECONDS = 5.0
SEND_SECONDS = 8.0
MAX_URL_LENGTH = 2000
# Metadata services of cloud providers, refused even though private networks are allowed:
# AWS, Azure, GCP and others (link-local, refused anyway), Alibaba, Oracle, AWS in IPv6.
METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(a)
    for a in ("169.254.169.254", "100.100.100.200", "192.0.0.192", "fd00:ec2::254")
)


class RefusedError(ValueError):
    """The address is not one the instance sends to; the message says why, without it."""


@dataclass(frozen=True)
class Parsed:
    scheme: str
    service: str


class _Guard:
    """What a send in progress knows; shared with the threads Apprise starts for it.

    It holds every socket created for the send. `close()` shuts them down when the send
    ends, whatever the plugin is doing with them: a server that keeps sending one byte now
    and then would otherwise keep the thread of the plugin, and its socket, for ever. Once
    closed, the guard refuses any new socket, name or connection of the send.
    """

    def __init__(self) -> None:
        self.blocked = False
        self.closed = False
        self._sockets: list[socket.socket] = []
        self._lock = threading.Lock()

    def track(self, sock: socket.socket) -> None:
        with self._lock:
            if self.closed:
                raise OSError("the send has ended")
            self._sockets.append(sock)

    def check(self) -> None:
        if self.closed:
            raise OSError("the send has ended")

    def close(self) -> None:
        with self._lock:
            self.closed = True
            sockets, self._sockets = self._sockets, []
        for sock in sockets:
            _shut(sock)


def _shut(sock: socket.socket) -> None:
    """Shut a socket down in both directions: a thread blocked reading it gets the end of
    the stream at once. Nothing happens to a socket already closed (its descriptor is -1,
    so no other connection can be hit). The TLS layer is left alone: the thread that reads
    it sees the connection end."""
    if sock.fileno() == -1:
        return
    with contextlib.suppress(OSError):
        socket.socket.shutdown(sock, socket.SHUT_RDWR)


# A context variable, not a thread local: Apprise runs a plugin in its own thread pool, and
# copies the context into it (contextvars.copy_context), so the guard follows the send.
_guard: contextvars.ContextVar[_Guard | None] = contextvars.ContextVar("guard", default=None)
_resolve = socket.getaddrinfo


def refused(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for an address refused to the test of an identity provider (docs/adr/0041) and
    for the metadata service of a cloud provider, also carried by an IPv6 address."""
    if forbidden_address(address):
        return True
    embedded = _embedded_ipv4(address) if isinstance(address, ipaddress.IPv6Address) else None
    return address in METADATA_ADDRESSES or embedded in METADATA_ADDRESSES


def _guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
    guard = _guard.get()
    if guard is not None:
        guard.check()
    infos = _resolve(host, port, *args, **kwargs)
    if guard is not None:
        for info in infos:
            address = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
            if refused(address):
                guard.blocked = True
                raise OSError("address refused by the instance")
    return infos


_original_init = socket.socket.__init__
_original_connect = socket.socket.connect


def _guarded_init(self: socket.socket, *args: Any, **kwargs: Any) -> None:
    # Also reached by the TLS socket that wraps a connection (`SSLSocket._create` calls it).
    _original_init(self, *args, **kwargs)
    guard = _guard.get()
    if guard is not None:
        try:
            guard.track(self)
        except OSError:
            self.close()
            raise


def _guarded_connect(self: socket.socket, address: Any) -> None:
    guard = _guard.get()
    if guard is not None:
        guard.check()
    _original_connect(self, address)
    if guard is not None and guard.closed:
        _shut(self)  # connected while the send was ending: `close()` came too early for it
        raise OSError("the send has ended")


_original_redirect_target = requests.Session.get_redirect_target


def _guarded_redirect_target(self: requests.Session, response: requests.Response) -> Any:
    if _guard.get() is not None:
        return None  # the 3xx answer is returned as is: the plugin counts it as a failure
    return _original_redirect_target(self, response)


def install() -> None:
    """Hook name resolution, sockets and redirects once; they act only inside `guarded()`."""
    if socket.getaddrinfo is not _guarded_getaddrinfo:
        socket.getaddrinfo = _guarded_getaddrinfo
    # Only over the original methods: a test that replaced one keeps its own.
    if socket.socket.__init__ is _original_init:
        socket.socket.__init__ = _guarded_init  # type: ignore[method-assign]
    if socket.socket.connect is _original_connect:
        socket.socket.connect = _guarded_connect  # type: ignore[method-assign,assignment]
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
        guard.close()


def _asset() -> AppriseAsset:
    # One service at a time, nothing on disk, and no address of an image: Apprise links its
    # icons on github.com, which the app of each person who receives a message would load.
    return AppriseAsset(
        async_mode=False, storage_mode="memory", image_url_mask="", image_url_logo=""
    )


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
        if literal is not None and refused(literal):
            raise RefusedError("address")
    plugin.verify_certificate = True
    plugin.socket_connect_timeout = TIMEOUT_SECONDS
    plugin.socket_read_timeout = TIMEOUT_SECONDS
    # `?retry=` and `?wait=` would call the service again, after the send gave up.
    plugin.retry = 0
    plugin.wait = 0.0
    # No image in a message either, whatever the options say (see `_asset`).
    for image in ("include_image", "footer_logo", "avatar"):
        if hasattr(plugin, image):
            setattr(plugin, image, False)
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

    The call returns within `SEND_SECONDS`: Apprise runs the plugin in its own thread and
    stops waiting for it then (the message counts as not sent). Every socket opened for the
    send is then shut down, so a server that keeps the connection open, sending one byte now
    and then, does not keep that thread either: it gets the end of the stream at once and
    finishes, and it can open no other socket. Only a name resolution in progress outlasts
    the send, for as long as the resolver of the system allows.
    """
    try:
        plugin = _plugin(crypto.decrypt(sealed))
        sender = apprise.Apprise(asset=_asset())
        sender.add(plugin)
        started = time.monotonic()
        with guarded():
            try:
                return bool(
                    sender.notify(
                        body=body, title=title, body_format=NotifyFormat.TEXT, timeout=SEND_SECONDS
                    )
                )
            finally:
                _log_out(plugin, SEND_SECONDS - (time.monotonic() - started))
    except Exception as exc:  # a plugin may raise anything; its message may carry the URL
        logger.warning("A notification could not be sent (%s).", type(exc).__name__)
        return False


def _log_out(plugin: Any, seconds: float) -> None:
    """The Matrix plugin logs out of the account it logged in to when it is garbage
    collected (`__del__`), in whatever thread drops it, outside the guard. Do it here
    instead, inside the guard and within the time left of the send, then drop the token,
    so that `__del__` has nothing left to send. Past that time the session stays open on
    the server of the person, as when the instance stops in the middle of a send."""
    if not isinstance(plugin, NotifyMatrix) or plugin.access_token is None:
        return
    if seconds > 0:
        context = contextvars.copy_context()
        worker = threading.Thread(target=context.run, args=(_quietly, plugin), daemon=True)
        worker.start()
        worker.join(seconds)
    plugin.access_token = None


def _quietly(plugin: NotifyMatrix) -> None:
    # The rules of Apprise's own `__del__`: no log out of a token typed as is, for instance.
    with contextlib.suppress(Exception):
        plugin.__del__()  # type: ignore[no-untyped-call]
