"""Image and upload helpers of the rooms, items and photos tests."""

import io
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

GPS = {1: "N", 2: (48.0, 51.0, 24.0), 3: "E", 4: (2.0, 21.0, 7.0)}


def image_bytes(
    fmt: str = "JPEG",
    size: tuple[int, int] = (64, 48),
    *,
    mode: str = "RGB",
    gps: bool = False,
    orientation: int | None = None,
    comment: bool = False,
) -> bytes:
    """A small image of the given format, optionally carrying location and other metadata."""
    image = Image.new(mode, size, "red" if mode != "1" else 1)
    options: dict[str, object] = {}
    if gps or orientation:
        exif = Image.Exif()
        exif[0x010F] = "Test camera"
        if gps:
            exif[0x8825] = GPS
        if orientation:
            exif[0x0112] = orientation
        options["exif"] = exif
    if comment and fmt == "JPEG":
        options["comment"] = b"secret comment"
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def noise_image(fmt: str = "PNG", side: int = 64) -> bytes:
    """An image that does not compress: a file of a few tens of kilobytes."""
    image = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def upload(
    data: bytes, name: str = "photo.jpg", content_type: str = "image/jpeg"
) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type=content_type)
