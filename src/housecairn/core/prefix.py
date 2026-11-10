"""Serving the application under a path prefix, such as `/housecairn` (docs/adr/0055).

The prefix comes from one of two places:

- `HOUSECAIRN_URL_PREFIX`, fixed at start-up. It is also Django's `FORCE_SCRIPT_NAME`, so
  every address Django builds starts with it, in the web process as in the task worker
  (reminder emails);
- a request header named by `HOUSECAIRN_URL_PREFIX_HEADER`, for a proxy whose prefix is
  only known at request time (Home Assistant's Ingress sends `X-Ingress-Path`). It is off
  unless that variable is set, and only counts from a trusted proxy:
  `core.proxy.ForwardedHeadersMiddleware` removes it from any other peer, as it removes the
  other forwarding headers.

`UrlPrefixMiddleware` applies it to each request. The proxy may pass the path with the
prefix or without it: a path that starts with the prefix loses it before the routes are
read. Without a prefix, nothing here changes anything.

A `next` must stay in the application: `in_application` checks that its path, once its dot
segments are resolved as a browser resolves them, still starts with the prefix.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from django.urls import Resolver404, ResolverMatch, get_script_prefix, resolve, set_script_prefix

# One segment of a prefix: unreserved characters of RFC 3986, never "." nor "..".
_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+")
# A header name (RFC 9110 token, without the characters no proxy uses in a name).
_HEADER_NAME = re.compile(r"[A-Za-z0-9-]+")
# STATIC_URL, relative so that Django and core.storage put the prefix in front of it.
STATIC_PATH = "static/"
# Longer than any proxy's prefix (Ingress: 60 characters or so), short enough for a log line.
MAX_LENGTH = 200


def _is_prefix(value: str) -> bool:
    if not value.startswith("/") or len(value) > MAX_LENGTH:
        return False
    segments = value[1:].split("/")
    return all(_SEGMENT.fullmatch(s) and s not in {".", ".."} for s in segments)


def parse_prefix(value: str) -> str:
    """`HOUSECAIRN_URL_PREFIX` as Django uses it: `""`, or `/a/b` without a trailing slash."""
    text = value.strip()
    if text in {"", "/"}:
        return ""
    text = text.rstrip("/")
    if not _is_prefix(text):
        raise ImproperlyConfigured(
            "HOUSECAIRN_URL_PREFIX must be a path such as /housecairn: segments of letters, "
            "digits and . _ ~ -, separated by single slashes."
        )
    return text


def parse_header_name(value: str) -> str:
    """`HOUSECAIRN_URL_PREFIX_HEADER`: a header name such as `X-Ingress-Path`, or `""`."""
    text = value.strip()
    if text and not _HEADER_NAME.fullmatch(text):
        raise ImproperlyConfigured(
            "HOUSECAIRN_URL_PREFIX_HEADER must be a header name such as X-Ingress-Path."
        )
    return text


def header_key() -> str | None:
    """The WSGI name of the prefix header, or None when no header may set the prefix."""
    name: str = settings.HOUSECAIRN_URL_PREFIX_HEADER
    return "HTTP_" + name.upper().replace("-", "_") if name else None


def prefix_of(request: HttpRequest) -> str:
    """The prefix for `request`: its header when allowed and valid, else the variable."""
    key = header_key()
    if key is not None:
        value = str(request.META.get(key, "")).strip().rstrip("/")
        if value and _is_prefix(value):
            return value
    configured: str = settings.HOUSECAIRN_URL_PREFIX
    return configured


def current() -> str:
    """The prefix of the request being served, `""` at the root."""
    return get_script_prefix().rstrip("/")


def in_application(url: str) -> bool:
    """True when `url` leads under the prefix once a browser has resolved its dot segments.

    At the root, the whole site is the application: the other checks of a `next` apply.
    """
    prefix = current()
    if not prefix:
        return True
    try:
        path = urlsplit(url).path
    except ValueError:
        return False
    if not path.startswith("/"):
        return False
    # A browser reads `\` as `/` and `%2e` as `.` in a path, then removes the dot segments.
    resolved = posixpath.normpath(unquote(path).replace("\\", "/"))
    return resolved == prefix or resolved.startswith(prefix + "/")


def resolve_url(url: str) -> ResolverMatch:
    """The route of an address built by `reverse`, prefix included; Resolver404 outside it."""
    path = urlsplit(url).path
    script = get_script_prefix()
    if script != "/":
        if path + "/" == script:
            path = script
        if not path.startswith(script):
            raise Resolver404({"path": path})
        path = "/" + path[len(script) :]
    return resolve(path)


def schema_servers(
    result: dict[str, Any], generator: Any, request: Any, public: bool
) -> dict[str, Any]:
    """drf-spectacular hook: under a prefix, the schema says where the API is."""
    prefix = current()
    if prefix:
        result["servers"] = [{"url": prefix}]
    return result


class UrlPrefixMiddleware:
    """Right after the forwarding headers: the prefix of the request, in its paths and cookies."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        prefix = prefix_of(request)
        if not prefix:
            return self.get_response(request)
        path_info = request.path_info
        if path_info == prefix or path_info.startswith(prefix + "/"):
            path_info = path_info[len(prefix) :] or "/"
        request.path_info = path_info
        request.path = prefix + path_info
        request.META["PATH_INFO"] = path_info
        request.META["SCRIPT_NAME"] = prefix
        set_script_prefix(prefix + "/")
        response = self.get_response(request)
        # Every cookie of the application, set or deleted, is limited to the prefix.
        for morsel in response.cookies.values():
            if morsel["path"] in {"", "/"}:
                morsel["path"] = prefix
        return response
