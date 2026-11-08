"""Fixtures of the rooms, items and photos tests (loaded with `pytest_plugins`)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from django.test import Client

from housecairn.accounts.models import User
from housecairn.homes.models import Home, Role
from housecairn.rooms import services
from housecairn.rooms.models import Item, Room


@pytest.fixture
def media_root(settings: object, tmp_path: Path) -> Path:
    """Photos of a test go to its own directory, never to the data volume."""
    settings.MEDIA_ROOT = tmp_path / "media"  # type: ignore[attr-defined]
    return tmp_path / "media"


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
