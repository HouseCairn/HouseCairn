"""Control and format characters are dropped from names, in the audit log and in the data."""

import pytest

from housecairn.accounts.models import User
from housecairn.audit import services as audit
from housecairn.audit.models import AuditEvent
from housecairn.core.text import without_control_characters
from housecairn.homes.models import Home
from housecairn.rooms import services as room_services
from housecairn.rooms.models import Item, Room
from tests.rooms_support import image_bytes, upload

pytest_plugins = ("tests.tasks_fixtures", "tests.rooms_fixtures")

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]

DIRTY = "Kit\x07chen\x1b[31m\u202eevil\u200b\ufeff"
CLEAN = "Kitchen[31mevil"


def test_the_helper_drops_control_and_format_characters_only() -> None:
    assert without_control_characters(DIRTY) == CLEAN
    assert without_control_characters("Café déjà 日本 🏠") == "Café déjà 日本 🏠"
    assert without_control_characters("a\tb\nc") == "abc"


class TestAuditTitles:
    def test_a_title_reaches_the_log_without_them(self, alice: User, alice_home: Home) -> None:
        audit.record_object("room.created", actor=alice, home_id=alice_home.id, title=DIRTY)
        event = AuditEvent.objects.filter(action="room.created").get()
        assert event.detail["title"] == CLEAN

    def test_line_breaks_still_become_a_space(self, alice: User, alice_home: Home) -> None:
        audit.record_object("room.created", actor=alice, home_id=alice_home.id, title="a\nb\x07c")
        assert AuditEvent.objects.get(action="room.created").detail["title"] == "a bc"


class TestNamesOfRoomsAndItems:
    def test_room_name_and_other_free_text(self, alice: User, alice_home: Home) -> None:
        room = room_services.create_room(alice, alice_home, name=DIRTY, kind="other", notes="a\nb")
        room.refresh_from_db()
        assert room.name == CLEAN
        assert room.notes == "a\nb"
        assert AuditEvent.objects.get(action="room.created").detail["title"] == CLEAN

    def test_memory_fields_of_a_room(self, alice: User, owner_room: Room) -> None:
        room_services.update_room(alice, owner_room, paint_brand=DIRTY, paint_colour=DIRTY)
        owner_room.refresh_from_db()
        assert owner_room.paint_brand == CLEAN
        assert owner_room.paint_colour == CLEAN

    def test_brand_and_provider_of_an_item(self, alice: User, owner_room: Room) -> None:
        item = room_services.create_item(
            alice, owner_room, name="Boiler", brand=DIRTY, contract_provider=DIRTY
        )
        item.refresh_from_db()
        assert item.brand == CLEAN
        assert item.contract_provider == CLEAN
        room_services.update_item(alice, item, name=DIRTY)
        assert Item.objects.get(pk=item.pk).name == CLEAN

    def test_caption_of_a_photo_on_add_and_update(self, alice: User, owner_room: Room) -> None:
        photo = room_services.add_photo(
            alice, upload=upload(image_bytes()), room=owner_room, caption=DIRTY
        )
        assert photo.caption == CLEAN
        room_services.update_photo(alice, photo, caption=DIRTY)
        photo.refresh_from_db()
        assert photo.caption == CLEAN
