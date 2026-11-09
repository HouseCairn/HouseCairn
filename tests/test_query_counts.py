"""The export of a home reads it in a number of queries that does not grow with its data.

Each test measures a small home, adds rows, and checks that the same work takes exactly as
many queries again: a query per row would show as a difference.
"""

from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from housecairn.homes import exports
from housecairn.homes.models import Home
from housecairn.projects.models import BudgetLine, Project
from housecairn.rooms.models import Item, Room
from housecairn.stock.models import Article, Movement

pytestmark = pytest.mark.django_db


def fill(home: Home, count: int) -> None:
    """Add `count` stock items and `count` projects, each tied to rooms and items."""
    rooms = Room.objects.bulk_create(
        [Room(home=home, name=f"Room {i}", position=i) for i in range(3)]
    )
    items = Item.objects.bulk_create(
        [Item(home=home, room=rooms[i], name=f"Item {i}") for i in range(3)]
    )
    articles = Article.objects.bulk_create(
        [Article(home=home, name=f"Article {i:03}") for i in range(count)]
    )
    Movement.objects.bulk_create(
        [
            Movement(
                home=home,
                article=a,
                kind="in",
                quantity=Decimal(2),
                delta=Decimal(2),
                occurred_on="2026-01-01",
            )
            for a in articles
        ]
    )
    for a in articles:
        a.compatible_items.set(items[:2])
        a.rooms.set(rooms[1:])
    projects = Project.objects.bulk_create(
        [Project(home=home, title=f"Project {i:03}") for i in range(count)]
    )
    BudgetLine.objects.bulk_create(
        [
            BudgetLine(home=home, project=p, label="Paint", nature="material", planned=Decimal(9))
            for p in projects
        ]
    )
    for p in projects:
        p.rooms.set(rooms[:2])


def queries(work: Any) -> int:
    with CaptureQueriesContext(connection) as context:
        work()
    return len(context.captured_queries)


def test_the_export_takes_as_many_queries_for_50_items_and_projects_as_for_5(
    alice_home: Home, django_assert_num_queries: Any
) -> None:
    fill(alice_home, 5)
    five = queries(lambda: exports.build_archive(alice_home))
    fill(alice_home, 45)
    assert Article.objects.filter(home=alice_home).count() == 50
    assert Project.objects.filter(home=alice_home).count() == 50
    with django_assert_num_queries(five):
        archive, _name = exports.build_archive(alice_home)
    assert archive.read()
