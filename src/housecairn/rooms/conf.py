"""Configuration of the rooms app (docs/adr/0030).

The size limit of a file is the instance setting `file_max_bytes` (docs/adr/0042): the
variable `HOUSECAIRN_PHOTO_MAX_BYTES`, read when Django starts, else the value set in
the interface, else 10 MB. It is read on use, so that a change applies without a restart.
"""

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
    """Largest accepted file, in bytes; ImproperlyConfigured when the value is unusable."""
    from housecairn.instance.config import get_setting

    raw = get_setting("file_max_bytes")
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
