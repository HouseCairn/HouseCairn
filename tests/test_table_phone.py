"""Tables on a phone (UX-02, design guide "Tables on a phone"): the markup of the component.

The width itself is measured in a browser (tests/e2e/table_widths.py, local). Here: every table
that overflowed at 360 px carries the common class, every value of a stacked table names itself,
and the table read column by column sits in a named scrolling region.
"""

from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.projects import services as project_services
from housecairn.projects.models import Project
from housecairn.rooms.models import Room
from housecairn.tasks import services as task_services

pytest_plugins = ("tests.rooms_fixtures", "tests.projects_fixtures")
pytestmark = pytest.mark.django_db

CSS = Path("src/housecairn/static/css/components.css")


class _Tables(HTMLParser):
    """Each table: its attributes, the region around it, and its body cells."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[dict[str, object]] = []
        self._regions: list[dict[str, str | None]] = []
        self._current: dict[str, object] | None = None
        self._cell: dict[str, str | None] | None = None
        self._cell_text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "div" and "table-scroll" in (values.get("class") or "").split():
            self._regions.append(values)
        elif tag == "table":
            self._current = {
                "class": (values.get("class") or "").split(),
                "region": self._regions[-1] if self._regions else None,
                "cells": [],
                "caption_ids": [],
            }
            self.tables.append(self._current)
        elif tag == "caption" and self._current is not None and values.get("id"):
            self._current["caption_ids"].append(values["id"])  # type: ignore[attr-defined]
        elif tag == "td" and self._current is not None:
            self._cell, self._cell_text = values, ""

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._current is not None and self._cell is not None:
            self._current["cells"].append((self._cell, self._cell_text.strip()))  # type: ignore[attr-defined]
            self._cell = None
        elif tag == "table":
            self._current = None


def tables_of(html: str) -> list[dict[str, object]]:
    parser = _Tables()
    parser.feed(html)
    return parser.tables


@pytest.fixture
def seeded(alice: User, alice_home: Home, owner_room: Room) -> Project:
    project = project_services.create_project(
        alice, alice_home, title="Paint the living room", rooms=[owner_room]
    )
    line = project_services.create_line(
        alice, project, label="Paint", nature="material", planned=Decimal("1250.50")
    )
    project_services.create_quote(
        alice, project, amount=Decimal("620.00"), status="accepted", budget_line=line
    )
    task_services.create_task(
        alice,
        alice_home,
        title="Clean the gutters",
        due_on=None,
        room=owner_room,
        labour_budget=Decimal("80"),
    )
    return project


def pages(home: Home, room: Room, project: Project) -> dict[str, str]:
    home_id = home.id
    return {
        "overview": reverse("budget:overview", kwargs={"home_id": home_id}),
        "rooms": reverse("budget:rooms", kwargs={"home_id": home_id}),
        "room": reverse("budget:room", kwargs={"home_id": home_id, "room_id": room.id}),
        "projects": reverse("budget:projects", kwargs={"home_id": home_id}),
        "tasks": reverse("budget:tasks", kwargs={"home_id": home_id}),
        "sheet": reverse("projects:detail", kwargs={"home_id": home_id, "project_id": project.id}),
    }


class TestStackedTables:
    def test_every_table_of_budget_and_the_project_sheet_is_stacked(
        self,
        signed_in: Client,
        alice_home: Home,
        owner_room: Room,
        seeded: Project,
    ) -> None:
        for name, address in pages(alice_home, owner_room, seeded).items():
            found = tables_of(signed_in.get(address).content.decode())
            assert found, name
            for table in found:
                assert "table-stack" in table["class"], name  # type: ignore[operator]

    def test_every_value_of_a_stacked_table_names_itself(
        self,
        signed_in: Client,
        alice_home: Home,
        owner_room: Room,
        seeded: Project,
    ) -> None:
        """A cell with content has a label (an empty one is not drawn on a phone)."""
        checked = 0
        for name, address in pages(alice_home, owner_room, seeded).items():
            for table in tables_of(signed_in.get(address).content.decode()):
                for attrs, text in table["cells"]:  # type: ignore[attr-defined]
                    if text:
                        assert attrs.get("data-label"), f"{name}: {text}"
                        checked += 1
        assert checked > 20

    def test_the_comparison_scrolls_in_a_named_region(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        seeded: Project,
    ) -> None:
        shed = project_services.create_project(alice, alice_home, title="Garden shed")
        address = reverse("projects:compare", kwargs={"home_id": alice_home.id})
        page = signed_in.get(address + f"?p={seeded.id}&p={shed.id}").content.decode()
        (table,) = tables_of(page)
        region = table["region"]
        assert region is not None
        assert region["role"] == "region"  # type: ignore[index]
        assert region["tabindex"] == "0"  # type: ignore[index]
        assert region["aria-labelledby"] in table["caption_ids"]  # type: ignore[index,operator]
        assert "table-stack" not in table["class"]  # type: ignore[operator]


class TestStylesheet:
    def test_the_component_is_below_56_rem_only(self) -> None:
        css = CSS.read_text(encoding="utf-8")
        assert ".table-stack" in css
        assert ".table-scroll" in css
        stacked = css.split("@media (max-width: 55.99rem)")[1]
        assert "content: attr(data-label)" in stacked
