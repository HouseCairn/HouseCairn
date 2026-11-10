"""Breadcrumbs on a computer (core/navigation.py, docs/developer/design-guide.md).

The trail follows the tree, not the origin; it is in the page for every width and
hidden below 56 rem by the style sheet, where the back link is enough.
"""

import re

import pytest
from django.test import Client
from django.urls import reverse

from housecairn.homes.models import Home
from housecairn.rooms.models import Item, Room

pytest_plugins = ("tests.rooms_fixtures", "tests.tasks_fixtures")

pytestmark = pytest.mark.django_db


def url(name: str, **kwargs: object) -> str:
    return reverse(name, kwargs=kwargs)


def trail(html: str) -> list[tuple[str | None, str]]:
    """(href or None, text) of each crumb, in order; empty when the page has none."""
    nav = re.search(r'<nav class="breadcrumbs" aria-label="[^"]*">(.*?)</nav>', html, re.S)
    if nav is None:
        return []
    items = re.findall(r"<li>(.*?)</li>", nav.group(1), re.S)
    found: list[tuple[str | None, str]] = []
    for item in items:
        link = re.search(r'<a href="([^"]*)">(.*?)</a>', item, re.S)
        if link:
            found.append((link.group(1), link.group(2)))
        else:
            current = re.search(r'<span aria-current="page">(.*?)</span>', item, re.S)
            assert current, item
            found.append((None, current.group(1)))
    return found


class TestThreeLevels:
    def test_an_item_shows_rooms_then_its_room_then_itself(
        self, signed_in: Client, alice_home: Home, owner_room: Room, owner_item: Item
    ) -> None:
        html = signed_in.get(
            url("rooms:item-detail", home_id=alice_home.id, item_id=owner_item.id)
        ).content.decode()
        assert trail(html) == [
            (url("rooms:list", home_id=alice_home.id), "Rooms"),
            (
                url("rooms:detail", home_id=alice_home.id, room_id=owner_room.id),
                owner_room.name,
            ),
            (None, owner_item.name),
        ]

    def test_the_last_crumb_is_the_current_page_and_the_others_are_links(
        self, signed_in: Client, alice_home: Home, owner_item: Item
    ) -> None:
        html = signed_in.get(
            url("rooms:item-detail", home_id=alice_home.id, item_id=owner_item.id)
        ).content.decode()
        assert html.count('aria-current="page">' + owner_item.name) == 1
        assert 'aria-label="Breadcrumbs"' in html

    def test_a_form_shows_its_title_as_the_last_crumb(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        html = signed_in.get(
            url("rooms:item-create", home_id=alice_home.id, room_id=owner_room.id)
        ).content.decode()
        assert [label for _, label in trail(html)] == ["Rooms", owner_room.name, "Add an item"]

    def test_the_trail_does_not_follow_the_origin(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        room = url("rooms:detail", home_id=alice_home.id, room_id=owner_room.id)
        budget = url("budget:rooms", home_id=alice_home.id)
        html = signed_in.get(f"{room}?next={budget}").content.decode()
        assert [label for _, label in trail(html)] == ["Rooms", owner_room.name]
        # The origin is not the parent: the back link stays, and it is not phone-only.
        assert re.search(r'<a class="back-link" href="[^"]*">', html)
        assert "data-phone-only" not in html


class TestBackLinkOnAComputer:
    def test_the_back_link_is_for_a_phone_when_the_trail_leads_to_the_parent(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        html = signed_in.get(
            url("rooms:detail", home_id=alice_home.id, room_id=owner_room.id)
        ).content.decode()
        assert 'class="back-link" href="' in html
        assert "data-phone-only" in html

    def test_a_form_keeps_its_back_link_on_a_computer(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        html = signed_in.get(
            url("rooms:edit", home_id=alice_home.id, room_id=owner_room.id)
        ).content.decode()
        assert trail(html)
        assert "data-phone-only" not in html


class TestNoTrailOnRoots:
    @pytest.mark.parametrize(
        "route", ["rooms:list", "tasks:today", "projects:list", "budget:overview", "tasks:list"]
    )
    def test_a_section_root_has_no_breadcrumbs(
        self, signed_in: Client, alice_home: Home, route: str
    ) -> None:
        html = signed_in.get(reverse(route, kwargs={"home_id": alice_home.id})).content.decode()
        assert 'class="breadcrumbs"' not in html

    def test_a_page_of_more_has_none(self, signed_in: Client) -> None:
        html = signed_in.get(reverse("notifications:index")).content.decode()
        assert 'class="breadcrumbs"' not in html


class TestHiddenOnAPhone:
    def test_the_style_sheet_hides_them_below_56rem(self) -> None:
        from pathlib import Path

        import housecairn

        css = (Path(housecairn.__file__).parent / "static/css/components.css").read_text()
        rule = css.split(".breadcrumbs {", 1)[1].split("}", 1)[0]
        assert "display: none" in rule
        assert "@media (min-width: 56rem)" in css.split(".breadcrumbs {", 1)[1]
