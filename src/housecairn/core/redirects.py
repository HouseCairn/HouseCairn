"""Where a `next` address may send someone: one rule for every page that reads it.

Django's `url_has_allowed_host_and_scheme` parses the address with `urlsplit`, which
drops tabs and line breaks first (bpo-43882). An address such as "//\\r" is then a
path for Django, but the response encodes it as "//%0D": a scheme-relative address,
whose host the browser then has to parse. Browsers refuse that host today (the
redirect fails), yet the check must not depend on it: an address with a control or
space character, one that starts with a backslash, or one that starts with two
slashes once backslashes are read as slashes, is refused before Django looks at it.
"""

import unicodedata

from django.http import HttpRequest
from django.utils.http import url_has_allowed_host_and_scheme


def has_safe_shape(url: str | None) -> bool:
    """False for an address no page of HouseCairn produces and a browser may misread.

    Refused: empty, any control, format or space character (Unicode categories C and
    Z, and whatever `str.isspace` sees), and an address that, after NFKC normalization,
    starts with `\\`, or with `//` once backslashes are read as slashes.
    """
    if not url:
        return False
    if any(unicodedata.category(c)[0] in "CZ" or c.isspace() for c in url):
        return False
    normalized = unicodedata.normalize("NFKC", url)
    return not normalized.startswith("\\") and not normalized.replace("\\", "/").startswith("//")


def is_safe_redirect(url: str | None, request: HttpRequest) -> bool:
    """True when `url` has a safe shape and stays on the host of `request`."""
    if not has_safe_shape(url):
        return False
    try:
        return url_has_allowed_host_and_scheme(
            url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        )
    except ValueError:  # urlsplit refuses an address such as "//[" or "http://[".
        return False
