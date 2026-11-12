"""Sending through Apprise, kept narrow (docs/adr/0043, 0059, 0064).

A channel makes the server call an address that a person typed. Apprise has no hook for
that: each plugin opens its own connections. So:

- only the schemes of `ALLOWED_SCHEMES` are accepted (`catalog`, docs/adr/0064): services
  reached over HTTP(S) or SMTP whose plugin fixes the method and the format of each
  request, and the path or its end (a typed prefix at most); nothing
  that runs a program, reads a local file or opens a raw socket, and no generic webhook
  (`json`, `xml`, `form`), whose URL chooses the method, the headers and the fields;
- a URL whose options make Apprise read a file (a template, a PGP key) is refused, and so
  is one whose options add headers or fields to the request (`+name`, `-name`, `:name`);
- while a message is sent, every name resolved in that thread is checked (`getaddrinfo`),
  and so is the address of every connection the send opens (`socket.connect`): it must be
  an IP address, the plugins connect to an address they resolved, and that address must
  not be refused (`refused`). Loopback, link-local, multicast, unspecified and reserved
  addresses are refused, as for the test of an identity provider (docs/adr/0041), and so
  are the metadata services of cloud providers (`METADATA_ADDRESSES`). Private networks
  and every other address that is not global are refused too, unless an administrator
  allows them (`notifications_private_networks`, for a ntfy or a Gotify of the local
  network); no HTTP redirect is followed;
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
from enum import Enum
from typing import Any

import apprise
import requests
from apprise import AppriseAsset, AppriseAttachment, NotifyFormat
from apprise.plugins.matrix import NotifyMatrix
from apprise.utils.parse import parse_qsd

from housecairn.core.netguard import METADATA_ADDRESSES, forbidden_address, is_public
from housecairn.core.netguard import embedded_ipv4 as _embedded_ipv4
from housecairn.instance import crypto
from housecairn.instance.config import get_setting
from housecairn.notifications import catalog

logger = logging.getLogger("housecairn.notifications")

# Services reached over HTTP(S) or SMTP whose plugin fixes the method and the format of
# every request, and lets no option choose the method, the path, the headers or the fields
# (docs/adr/0064 reviews every plugin; `catalog` lists the ones accepted).
ALLOWED_SCHEMES = catalog.ALLOWED_SCHEMES
# Query options that Apprise turns into extra headers (+), removed fields (-) or added
# fields (:) of the request.
EXTRA_PREFIXES = ("qsd+", "qsd-", "qsd:")
# Each wait of a socket (connect, read), and the whole send to one channel.
TIMEOUT_SECONDS = 5.0
SEND_SECONDS = 8.0
MAX_URL_LENGTH = 2000


class RefusedError(ValueError):
    """The address is not one the instance sends to; the message says why, without it.

    Codes: `invalid`, `scheme`, `fields`, `options`, `address`, and `private` for an address
    that only the rule of private networks refuses (an administrator may allow it).
    """


class Outcome(Enum):
    """How a send ended: `PRIVATE` when nothing was sent because the address is on a private
    network that the instance does not allow, so that the person can be told why."""

    SENT = "sent"
    FAILED = "failed"
    PRIVATE = "private"


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

    def __init__(self, *, private_networks: bool = False) -> None:
        self.private_networks = private_networks
        self.blocked = False  # an address was refused
        self.private = False  # ... by the rule of private networks only
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


def refused(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address, *, private_networks: bool = False
) -> bool:
    """Whether a channel may not reach this address (docs/adr/0059).

    Always refused: what the test of an identity provider refuses (docs/adr/0041), and the
    metadata service of a cloud provider, also when an IPv6 address carries one. Unless
    `private_networks` (the setting of the same name), every address that is not global is
    refused too (`is_public`): private networks, the shared address space, unique local
    IPv6 addresses.
    """
    return refusal(address, private_networks=private_networks) is not None


def refusal(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address, *, private_networks: bool = False
) -> str | None:
    """Why `refused` refuses an address: `address` (always refused), `private` (refused by
    the rule of private networks only, which an administrator may lift), or None."""
    if forbidden_address(address):
        return "address"
    embedded = _embedded_ipv4(address) if isinstance(address, ipaddress.IPv6Address) else None
    if address in METADATA_ADDRESSES or embedded in METADATA_ADDRESSES:
        return "address"
    if not private_networks and not is_public(address):
        return "private"
    return None


def private_networks_allowed() -> bool:
    """The setting in force; read in the thread that sends, before the guard."""
    return bool(get_setting("notifications_private_networks"))


def _judge(guard: _Guard, text: str) -> None:
    """Refuse an address of the send (a text, as in a socket address) that is not allowed."""
    try:
        address = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        guard.blocked = True
        raise OSError("address refused by the instance") from None
    reason = refusal(address, private_networks=guard.private_networks)
    if reason is not None:
        guard.blocked = True
        guard.private = reason == "private"
        raise OSError("address refused by the instance")


def _guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
    guard = _guard.get()
    if guard is not None:
        guard.check()
    infos = _resolve(host, port, *args, **kwargs)
    if guard is not None:
        for info in infos:
            _judge(guard, str(info[4][0]))
    return infos


_original_init = socket.socket.__init__
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex


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


def _check_target(guard: _Guard, sock: socket.socket, address: Any) -> None:
    """The address a socket of the send connects to: an IP address that is allowed.

    The plugins resolve a name first (`getaddrinfo`, checked above) and connect to one of
    its addresses. A name given to `connect` itself would be resolved by the C library,
    out of the guard's sight, so it is refused; so is any socket that is not IPv4 or IPv6
    (a local socket, for one). An IPv6 address that carries an IPv4 one is judged by it.
    """
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        guard.blocked = True
        raise OSError("address refused by the instance")
    host = address[0] if isinstance(address, tuple) and address else None
    if not isinstance(host, str):
        guard.blocked = True
        raise OSError("address refused by the instance")
    _judge(guard, host)


def _guarded_connect(self: socket.socket, address: Any) -> None:
    guard = _guard.get()
    if guard is not None:
        guard.check()
        _check_target(guard, self, address)
    _original_connect(self, address)
    if guard is not None and guard.closed:
        _shut(self)  # connected while the send was ending: `close()` came too early for it
        raise OSError("the send has ended")


def _guarded_connect_ex(self: socket.socket, address: Any) -> int:
    guard = _guard.get()
    if guard is not None:
        guard.check()
        _check_target(guard, self, address)
    result = _original_connect_ex(self, address)
    if guard is not None and guard.closed:
        _shut(self)
        raise OSError("the send has ended")
    return result


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
    if socket.socket.connect_ex is _original_connect_ex:
        socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign,assignment]
    requests.Session.get_redirect_target = _guarded_redirect_target  # type: ignore[method-assign,assignment]
    for name in ("apprise", "urllib3"):
        quiet = logging.getLogger(name)
        quiet.setLevel(logging.CRITICAL + 1)
        quiet.propagate = False


@contextlib.contextmanager
def guarded(*, private_networks: bool = False) -> Iterator[_Guard]:
    install()
    guard = _Guard(private_networks=private_networks)
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


def _plugin(url: str, *, private_networks: bool = False) -> Any:
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
    # The schemes of the class: an instance may use the same names for something else (the
    # Kodi plugin keeps the version of its protocol in `protocol`).
    protocols = {
        p.lower()
        for attr in ("protocol", "secure_protocol")
        for p in _as_tuple(getattr(type(plugin), attr, None))
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
        reason = None if literal is None else refusal(literal, private_networks=private_networks)
        if reason is not None:
            raise RefusedError(reason)
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
    if not isinstance(value, (tuple, list, set, frozenset)):
        return ()
    return tuple(v for v in value if isinstance(v, str))


def parse(url: Any) -> Parsed:
    """Check an address typed by a person; `RefusedError` with a reason code if refused.

    An address typed as is (an IP address for host) is judged here, with the setting of
    private networks in force; a name is judged each time a message is sent.
    """
    text = url.strip() if isinstance(url, str) else ""
    plugin = _plugin(text, private_networks=private_networks_allowed())
    return Parsed(text.split("://", 1)[0].lower(), str(plugin.service_name)[:60])


def seal(url: str) -> str:
    return crypto.encrypt(url.strip())


def send(sealed: str, *, title: str, body: str) -> bool:
    """Send plain text to one channel. True when the service accepted it; never raises."""
    return deliver(sealed, title=title, body=body) is Outcome.SENT


def deliver(sealed: str, *, title: str, body: str) -> Outcome:
    """Send plain text to one channel, and say how it ended; never raises.

    Apprise escapes the plain text for the format of the channel (HTML, Markdown), so a
    title typed by a person cannot change the markup of the message.

    The call returns within `SEND_SECONDS`: Apprise runs the plugin in its own thread and
    stops waiting for it then (the message counts as not sent). Every socket opened for the
    send is then shut down, so a server that keeps the connection open, sending one byte now
    and then, does not keep that thread either: it gets the end of the stream at once and
    finishes, and it can open no other socket. Only a name resolution in progress outlasts
    the send, for as long as the resolver of the system allows.
    """
    private = False
    try:
        private_networks = private_networks_allowed()
        try:
            plugin = _plugin(crypto.decrypt(sealed), private_networks=private_networks)
        except RefusedError as exc:
            private = str(exc) == "private"
            raise
        sender = apprise.Apprise(asset=_asset())
        sender.add(plugin)
        started = time.monotonic()
        with guarded(private_networks=private_networks) as guard:
            try:
                sent = bool(
                    sender.notify(
                        body=body, title=title, body_format=NotifyFormat.TEXT, timeout=SEND_SECONDS
                    )
                )
            finally:
                _log_out(plugin, SEND_SECONDS - (time.monotonic() - started))
                private = guard.private
        if sent:
            return Outcome.SENT
    except Exception as exc:  # a plugin may raise anything; its message may carry the URL
        if not private:
            logger.warning("A notification could not be sent (%s).", type(exc).__name__)
    if private:
        logger.warning(
            "A notification was not sent: its address is on a private network, which the "
            "instance does not allow (notifications_private_networks)."
        )
        return Outcome.PRIVATE
    return Outcome.FAILED


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
