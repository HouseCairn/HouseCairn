"""Addresses made to leave the application (docs/adr/0055, section of 2026-11-10).

An address that is sent away, printed or copied elsewhere (the links of emails and
invitations, the address a QR label holds, a calendar feed and the links inside it, the
address of the first-account screen in the log) is always built here, on the public address
of the instance: the scheme and host of `HOUSECAIRN_SITE_URL` (else, for an address built
during a request, those of the request), then the fixed prefix `HOUSECAIRN_URL_PREFIX`, then
the route. Without a public address, the links of the task worker (reminders, report alerts)
are left out, and the log shows the path of the first-account screen only.

It never takes the prefix of the request: a prefix given by a proxy header, such as Home
Assistant's Ingress path, only works through that proxy, and its token changes. Addresses
used inside a page (navigation, forms, static files) keep the prefix of the request: they
come from `reverse` and `{% url %}` as before.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.urls import get_script_prefix


def external_url(address: str, site: str) -> str:
    """`address`, a path built by `reverse` (query and fragment kept), on the public address.

    `site` is a scheme and host, such as `https://home.example.com` (a trailing slash is
    ignored). The prefix of the request, if `address` starts with it, is replaced by
    `HOUSECAIRN_URL_PREFIX`. Without a `site`, there is no public address: `""`.
    """
    base = site.rstrip("/")
    if not base:
        return ""
    parts = urlsplit(address)
    path = parts.path or "/"
    script = get_script_prefix()
    if script != "/":
        if path + "/" == script:
            path = "/"
        elif path.startswith(script):
            path = "/" + path[len(script) :]
    fixed: str = settings.HOUSECAIRN_URL_PREFIX
    return base + urlunsplit(("", "", fixed + path, parts.query, parts.fragment))
