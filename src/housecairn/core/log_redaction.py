"""Keep the secret of a calendar feed out of the logs (docs/adr/0052).

The address of a feed, `/calendar/feed/<secret>.ics`, is the credential: whoever reads it in
a log can read the calendar. The application writes the path of a request in two places, the
access log of gunicorn and the `django.request` warning of an answer with a 4xx code (a 429 on
a valid secret, for one). Both go through `redact`. The reverse proxy writes it too, and is not
ours to change: the guide says how to configure it.
"""

import logging
import re
from typing import Any

MASK = "***"
# The secret is one path segment between the fixed prefix and ".ics". The slashes and the dot
# may be percent-encoded by a client, and gunicorn writes the request line as received. The
# secret is made of letters, digits, "-" and "_" only, so it stops at any other character: a
# query string or the next word stays readable.
_FEED_ADDRESS = re.compile(
    r"((?:/|%2F)calendar(?:/|%2F)feed(?:/|%2F))[^/?#%\s\"'<>]+((?:\.|%2E)ics)", re.IGNORECASE
)


def redact(text: str) -> str:
    """`text` with the secret of any feed address replaced by `***`."""
    return _FEED_ADDRESS.sub(lambda m: m.group(1) + MASK + m.group(2), text)


class RedactFeedAddresses(logging.Filter):
    """A log filter: whatever a record says, a feed address is written without its secret."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = redact(message)
        if masked != message:
            record.msg, record.args = masked, None
        return True


def redact_atoms(atoms: dict[str, Any]) -> dict[str, Any]:
    """The text atoms of a gunicorn access line (`%(r)s`, `%(U)s`, headers...), redacted."""
    return {k: redact(v) if isinstance(v, str) else v for k, v in atoms.items()}
