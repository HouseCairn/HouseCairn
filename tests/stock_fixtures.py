"""Fixtures of the stock tests (loaded with `pytest_plugins` after `tests.rooms_fixtures`)."""

from decimal import Decimal

import pytest

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.rooms import services as room_services
from housecairn.rooms.models import Item
from housecairn.stock import services
from housecairn.stock.models import Article


@pytest.fixture
def article(alice: User, alice_home: Home, owner_item: Item) -> Article:
    return services.create_article(
        alice,
        alice_home,
        compatible_items=[owner_item],
        name="Boiler filter",
        manufacturer_reference="BF-200",
        unit="pieces",
        threshold=Decimal("2"),
        storage_location="Garage",
    )


@pytest.fixture
def foreign_item(bob: User, bob_home: Home) -> Item:
    """An item of another home."""
    room = room_services.create_room(bob, bob_home, name="Hall")
    return room_services.create_item(bob, room, name="Foreign boiler")


@pytest.fixture
def foreign_article(bob: User, bob_home: Home) -> Article:
    return services.create_article(bob, bob_home, name="Foreign filter")
