"""Shared helpers of the rooms, items and photos tests."""

import io
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from housecairn.accounts.models import User
from housecairn.homes.models import Home, Role
from housecairn.rooms import services
from housecairn.rooms.models import Item, Room

GPS = {1: "N", 2: (48.0, 51.0, 24.0), 3: "E", 4: (2.0, 21.0, 7.0)}


@pytest.fixture
def media_root(settings: object, tmp_path: Path) -> Path:
    """Photos of a test go to its own directory, never to the data volume."""
    settings.MEDIA_ROOT = tmp_path / "media"  # type: ignore[attr-defined]
    return tmp_path / "media"


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


@pytest.fixture
def owner_room(alice: User, alice_home: Home) -> Room:
    return services.create_room(alice, alice_home, name="Living room")


@pytest.fixture
def owner_item(alice: User, owner_room: Room) -> Item:
    return services.create_item(alice, owner_room, name="Boiler", brand="Acme")


@pytest.fixture
def reader(
    make_user: Callable[..., User], alice_home: Home, add_member: Callable[..., object]
) -> User:
    user = make_user("reader@example.com")
    add_member(alice_home, user, Role.READ_ONLY)
    return user


@pytest.fixture
def member(
    make_user: Callable[..., User], alice_home: Home, add_member: Callable[..., object]
) -> User:
    user = make_user("member@example.com")
    add_member(alice_home, user, Role.MEMBER)
    return user


@pytest.fixture
def site_admin(make_user: Callable[..., User]) -> User:
    """Administrator of the instance, member of no home."""
    return make_user("admin@example.com", is_staff=True, is_superuser=True)


@pytest.fixture
def signed_in(client: Client, alice: User) -> Client:
    client.force_login(alice)
    return client
