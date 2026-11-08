"""Fixtures of the tasks tests (loaded with `pytest_plugins`)."""

import datetime

import pytest

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.rooms.models import Item, Room
from housecairn.tasks import services
from housecairn.tasks.models import Occurrence, Task

pytest_plugins = ("tests.rooms_fixtures",)

TODAY = datetime.date(2026, 6, 15)


@pytest.fixture
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> datetime.date:
    """A fixed day, so that late and not late do not depend on the date of the run."""
    monkeypatch.setattr(services, "today", lambda: TODAY)
    return TODAY


@pytest.fixture
def owner_task(alice: User, alice_home: Home, owner_room: Room, owner_item: Item) -> Task:
    return services.create_task(
        alice,
        alice_home,
        title="Change the smoke detector battery",
        room=owner_room,
        item=owner_item,
        due_on=TODAY - datetime.timedelta(days=2),
        repeat_mode="after_last",
        repeat_unit="year",
        repeat_interval=1,
    )


@pytest.fixture
def owner_occurrence(owner_task: Task) -> Occurrence:
    occurrence = services.open_occurrence_of(owner_task)
    assert occurrence is not None
    return occurrence
