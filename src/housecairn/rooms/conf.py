"""Configuration of the rooms app (docs/adr/0030).

The size limit of a photo is read here, from `settings.HOUSECAIRN_PHOTO_MAX_BYTES`
if a deployment or a test sets it, else from the environment variable of the same
name, else the default. Reading it on use keeps the value testable.
"""

import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PHOTO_MAX_BYTES_VARIABLE = "HOUSECAIRN_PHOTO_MAX_BYTES"
DEFAULT_PHOTO_MAX_BYTES = 10 * 1024 * 1024
MIN_PHOTO_MAX_BYTES = 10 * 1024
MAX_PHOTO_MAX_BYTES = 100 * 1024 * 1024

# Not configurable: they bound the work done on an image and the space it takes.
MAX_PIXELS = 40_000_000
MAX_STORED_SIDE = 2560
THUMBNAIL_SIDE = 360
MAX_PHOTOS_PER_TARGET = 30
# Allowance, over the file limit, for the other parts of a multipart request.
MULTIPART_OVERHEAD = 256 * 1024


def photo_max_bytes() -> int:
    """Largest accepted photo, in bytes; ImproperlyConfigured when the value is unusable."""
    raw = getattr(settings, PHOTO_MAX_BYTES_VARIABLE, None)
    if raw is None:
        raw = os.environ.get(PHOTO_MAX_BYTES_VARIABLE, "").strip() or DEFAULT_PHOTO_MAX_BYTES
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(f"{PHOTO_MAX_BYTES_VARIABLE} must be a whole number.") from exc
    if not MIN_PHOTO_MAX_BYTES <= value <= MAX_PHOTO_MAX_BYTES:
        raise ImproperlyConfigured(
            f"{PHOTO_MAX_BYTES_VARIABLE} must be between {MIN_PHOTO_MAX_BYTES} "
            f"and {MAX_PHOTO_MAX_BYTES} bytes."
        )
    return value
