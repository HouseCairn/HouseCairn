"""Fixtures of the projects tests (loaded with `pytest_plugins` after `tests.rooms_fixtures`)."""

from decimal import Decimal

import pytest
from django.utils import translation

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.projects import services
from housecairn.projects.models import BudgetLine, Project, Quote

pytest_plugins = ("tests.rooms_fixtures",)


@pytest.fixture(autouse=True)
def _english() -> object:
    """Read labels in English whatever language an earlier test left active."""
    with translation.override("en"):
        yield


@pytest.fixture
def living_room_project(alice: User, alice_home: Home) -> Project:
    """The "Peinture du salon" scenario: 300 of paint and 500 of labour planned, 800 in all."""
    project = services.create_project(alice, alice_home, title="Paint the living room")
    services.create_line(
        alice, project, label="Paint", nature="material", planned=Decimal("300.00")
    )
    services.create_line(alice, project, label="Painter", nature="labour", planned=Decimal("500"))
    return project


@pytest.fixture
def labour_line(living_room_project: Project) -> BudgetLine:
    return BudgetLine.objects.get(project=living_room_project, label="Painter")


@pytest.fixture
def quote(alice: User, living_room_project: Project) -> Quote:
    return services.create_quote(
        alice,
        living_room_project,
        contractor=services.contractor_named(alice, living_room_project.home, "Painter A"),
        amount=Decimal("620.00"),
        status="received",
    )


@pytest.fixture
def foreign_project(bob: User, bob_home: Home) -> Project:
    project = services.create_project(bob, bob_home, title="Foreign project", budget=Decimal("900"))
    services.create_quote(bob, project, amount=Decimal("100"))
    return project
