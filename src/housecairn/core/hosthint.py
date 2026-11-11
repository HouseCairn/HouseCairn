"""The hint of the 400 page shown for a host name the instance does not answer to.

A host that serves HouseCairn for someone else (a Home Assistant add-on, a third-party
image) knows which setting to change when a name is refused; the application does not. It
sets `HOUSECAIRN_DISALLOWED_HOST_HINT` to that sentence and the 400 page shows it, instead
of the generic one. The text is shown as plain text, in the language its author wrote it.
"""

from __future__ import annotations

import unicodedata

from django.core.exceptions import ImproperlyConfigured

# A sentence or two; the page is public, so a longer text is more likely a mistake.
MAX_LENGTH = 300


def parse_hint(value: str) -> str:
    """`HOUSECAIRN_DISALLOWED_HOST_HINT` as the page shows it: `""`, or a short plain text."""
    text = value.strip()
    if len(text) > MAX_LENGTH:
        raise ImproperlyConfigured(
            f"HOUSECAIRN_DISALLOWED_HOST_HINT must be at most {MAX_LENGTH} characters long."
        )
    if any(unicodedata.category(char) == "Cc" for char in text):
        raise ImproperlyConfigured(
            "HOUSECAIRN_DISALLOWED_HOST_HINT must not contain control characters or line breaks."
        )
    return text
