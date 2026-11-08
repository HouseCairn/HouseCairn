"""Checking and re-encoding an uploaded photo (docs/adr/0030).

The type is decided by decoding the content, restricted to JPEG (multi-picture JPEG
included), PNG and WebP: the file name and the header sent by the client are never
looked at. The image is then
decoded in full, turned upright, and written again from its pixels, so that nothing
of the original file survives: EXIF (location included), XMP, comments and any
bytes appended or hidden in the file are gone. Only the colour profile is kept.
"""

import io
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError

from housecairn.rooms import conf

# Pillow format name -> (content type, extension); the only formats ever decoded.
FORMATS: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


@dataclass(frozen=True)
class ProcessedPhoto:
    content_type: str
    extension: str
    data: bytes
    thumbnail: bytes
    width: int
    height: int


def _invalid() -> ValidationError:
    return ValidationError(_("This file is not a valid JPEG, PNG or WebP image."))


def _decode(data: bytes) -> Image.Image:
    # The size is read from the header before decoding: a 40 megapixel image still costs
    # a few seconds and several hundred MB (docs/adr/0030).
    try:
        image = Image.open(io.BytesIO(data), formats=list(FORMATS))
        if image.width * image.height > conf.MAX_PIXELS:
            raise ValidationError(_("This image is too large (more than 40 megapixels)."))
        image.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise _invalid() from None
    if image.format not in (*FORMATS, "MPO"):  # pragma: no cover - `formats` restricts it
        raise _invalid()
    return image


def _encode(image: Image.Image, fmt: str, **options: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def _flatten(image: Image.Image) -> Image.Image:
    """RGB version of the image, transparency on white (for JPEG)."""
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def process(data: bytes) -> ProcessedPhoto:
    """Validate and re-encode; raises ValidationError for anything but a decodable image."""
    original = _decode(data)
    # A multi-picture JPEG (phones in portrait or HDR) opens as "MPO": it is a JPEG whose
    # first image is the photo. Re-encoding keeps that image only.
    fmt = "JPEG" if original.format == "MPO" else str(original.format)
    profile = original.info.get("icc_profile")
    upright = ImageOps.exif_transpose(original)
    # Keep nothing from the file but the colour profile and, for a palette image, the
    # index of its transparent colour.
    upright.info = {k: v for k, v in original.info.items() if k in ("icc_profile", "transparency")}
    if max(upright.size) > conf.MAX_STORED_SIDE:
        upright.thumbnail((conf.MAX_STORED_SIDE, conf.MAX_STORED_SIDE), Image.Resampling.LANCZOS)
    profile_options = {"icc_profile": profile} if profile else {}

    if fmt == "JPEG":
        body = upright if upright.mode in ("RGB", "L", "CMYK") else _flatten(upright)
        stored = _encode(body, "JPEG", quality=85, optimize=True, **profile_options)
    elif fmt == "WEBP":
        body = upright if upright.mode in ("RGB", "RGBA") else upright.convert("RGBA")
        stored = _encode(body, "WEBP", quality=85, **profile_options)
    else:
        stored = _encode(upright, "PNG", optimize=True, **profile_options)

    small = _flatten(upright)
    small.thumbnail((conf.THUMBNAIL_SIDE, conf.THUMBNAIL_SIDE), Image.Resampling.LANCZOS)
    thumbnail = _encode(small, "JPEG", quality=80, optimize=True)
    content_type, extension = FORMATS[fmt]
    return ProcessedPhoto(
        content_type=content_type,
        extension=extension,
        data=stored,
        thumbnail=thumbnail,
        width=upright.width,
        height=upright.height,
    )
