"""Rooms, room memory and items: services, web screens, roles, isolation (docs/adr/0029)."""

import datetime
import re
import uuid

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.rooms import forms, services
from housecairn.rooms.models import Item, Photo, Room, validate_links
from tests.rooms_support import image_bytes, upload

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]


def url(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"rooms:{name}", kwargs={"home_id": home.id, **kwargs})


class TestServices:
    def test_only_the_name_is_required(self, alice: User, alice_home: Home) -> None:
        room = services.create_room(alice, alice_home, name="Hall")
        assert (room.kind, room.notes, room.paint_brand) == ("other", "", "")
        with pytest.raises(ValidationError):
            services.create_room(alice, alice_home, name="")

    def test_rooms_keep_their_order_of_creation(self, alice: User, alice_home: Home) -> None:
        names = ["Hall", "Kitchen", "Garage"]
        for name in names:
            services.create_room(alice, alice_home, name=name)
        assert [r.name for r in services.rooms_of(alice_home)] == names
        assert [r.position for r in services.rooms_of(alice_home)] == [0, 1, 2]

    def test_update_and_memory(self, alice: User, owner_room: Room) -> None:
        services.update_room(
            alice, owner_room, name="Lounge", paint_brand="Acme", memory_notes="half a tin"
        )
        owner_room.refresh_from_db()
        assert (owner_room.name, owner_room.paint_brand, owner_room.has_memory) == (
            "Lounge",
            "Acme",
            True,
        )

    def test_unknown_field_is_refused(self, alice: User, owner_room: Room) -> None:
        with pytest.raises(ValueError, match="position"):
            services.update_room(alice, owner_room, position=5)

    def test_notes_are_limited(self, alice: User, owner_room: Room) -> None:
        with pytest.raises(ValidationError):
            services.update_room(alice, owner_room, notes="x" * 4001)

    def test_reorder_and_move(self, alice: User, alice_home: Home) -> None:
        a, b, c = (services.create_room(alice, alice_home, name=n) for n in "abc")
        services.reorder_rooms(alice, alice_home, [c.id, a.id])
        assert [r.name for r in services.rooms_of(alice_home)] == ["c", "a", "b"]
        services.move_room(alice, b, "up")
        assert [r.name for r in services.rooms_of(alice_home)] == ["c", "b", "a"]
        services.move_room(alice, c, "up")  # already first: nothing changes
        services.move_room(alice, a, "down")  # already last: nothing changes
        assert [r.name for r in services.rooms_of(alice_home)] == ["c", "b", "a"]
        with pytest.raises(ValidationError):
            services.move_room(alice, a, "sideways")

    def test_reorder_refuses_duplicates_and_foreign_rooms(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home
    ) -> None:
        mine = services.create_room(alice, alice_home, name="mine")
        theirs = services.create_room(bob, bob_home, name="theirs")
        with pytest.raises(ValidationError):
            services.reorder_rooms(alice, alice_home, [mine.id, mine.id])
        with pytest.raises(ValidationError):
            services.reorder_rooms(alice, alice_home, [theirs.id])

    def test_deleting_a_room_deletes_its_items_and_photos(
        self, alice: User, owner_room: Room, owner_item: Item
    ) -> None:
        services.delete_room(alice, owner_room)
        assert not Room.objects.filter(id=owner_room.id).exists()
        assert not Item.objects.filter(id=owner_item.id).exists()
        assert Item.all_objects.get(id=owner_item.id).is_deleted

    def test_items(self, alice: User, owner_room: Room) -> None:
        item = services.create_item(
            alice,
            owner_room,
            name="Stove",
            kind="equipment",
            installed_on=datetime.date(2021, 9, 14),
            warranty_ends_on=datetime.date(2031, 9, 14),
            contract_url="https://example.com/contract",
            links=[{"url": "https://example.com/manual", "label": "Manual"}],
        )
        assert item.warranty_state(datetime.date(2026, 1, 1)) == "active"
        assert item.warranty_state(datetime.date(2032, 1, 1)) == "expired"
        assert Item(name="x").warranty_state(datetime.date(2026, 1, 1)) == "none"
        services.delete_item(alice, item)
        assert not Item.objects.filter(id=item.id).exists()

    def test_moving_an_item_to_another_room(
        self, alice: User, alice_home: Home, owner_room: Room, owner_item: Item
    ) -> None:
        kitchen = services.create_room(alice, alice_home, name="Kitchen")
        services.update_item(alice, owner_item, room=kitchen, name="Oven")
        owner_item.refresh_from_db()
        assert (owner_item.room_id, owner_item.name) == (kitchen.id, "Oven")

    def test_an_item_cannot_move_to_a_room_of_another_home(
        self, alice: User, bob: User, bob_home: Home, owner_item: Item
    ) -> None:
        theirs = services.create_room(bob, bob_home, name="theirs")
        with pytest.raises(ValidationError):
            services.update_item(alice, owner_item, room=theirs)

    def test_search_by_name(self, alice: User, alice_home: Home, owner_room: Room) -> None:
        services.create_item(alice, owner_room, name="Smoke detector")
        services.create_item(alice, owner_room, name="Boiler")
        result = services.search(alice_home, " smoke ")
        assert [i.name for i in result.items] == ["Smoke detector"]
        assert result.rooms == []
        assert [r.name for r in services.search(alice_home, "LIVING").rooms] == ["Living room"]
        assert not services.search(alice_home, "   ")

    def test_search_stays_in_the_home(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home
    ) -> None:
        services.create_room(bob, bob_home, name="Secret cellar")
        assert not services.search(alice_home, "cellar")


class TestRoles:
    def test_read_only_cannot_write_anything(
        self, reader: User, owner_room: Room, owner_item: Item
    ) -> None:
        with pytest.raises(PermissionDenied):
            services.create_room(reader, owner_room.home, name="x")
        with pytest.raises(PermissionDenied):
            services.update_room(reader, owner_room, name="x")
        with pytest.raises(PermissionDenied):
            services.delete_room(reader, owner_room)
        with pytest.raises(PermissionDenied):
            services.reorder_rooms(reader, owner_room.home, [owner_room.id])
        with pytest.raises(PermissionDenied):
            services.create_item(reader, owner_room, name="x")
        with pytest.raises(PermissionDenied):
            services.update_item(reader, owner_item, name="x")
        with pytest.raises(PermissionDenied):
            services.delete_item(reader, owner_item)

    def test_a_member_writes(self, member: User, owner_room: Room) -> None:
        assert services.create_item(member, owner_room, name="Lamp").pk

    def test_a_stranger_writes_nothing(self, bob: User, owner_room: Room, site_admin: User) -> None:
        for stranger in (bob, site_admin):
            with pytest.raises(PermissionDenied):
                services.create_item(stranger, owner_room, name="x")


class TestModels:
    @pytest.mark.parametrize(
        "value",
        [
            "not a list",
            [{"url": "https://example.com"}] * 11,
            [{"label": "no url"}],
            [{"url": "https://example.com", "other": 1}],
            [{"url": 1}],
            [{"url": "https://example.com", "label": "x" * 101}],
            [{"url": "javascript:alert(1)"}],
            [{"url": "ftp://example.com/file"}],
            ["https://example.com"],
        ],
    )
    def test_links_are_checked(self, value: object) -> None:
        with pytest.raises(ValidationError):
            validate_links(value)

    def test_a_contract_link_is_a_web_address(self, alice: User, owner_room: Room) -> None:
        with pytest.raises(ValidationError):
            services.create_item(alice, owner_room, name="x", contract_url="javascript:alert(1)")

    def test_text_to_links_and_back(self) -> None:
        links = forms.text_to_links("https://example.com/a Manual\n\n  https://example.com/b  ")
        assert links == [
            {"url": "https://example.com/a", "label": "Manual"},
            {"url": "https://example.com/b"},
        ]
        assert forms.links_to_text(links) == "https://example.com/a Manual\nhttps://example.com/b"

    def test_strings(self, owner_room: Room, owner_item: Item) -> None:
        assert (str(owner_room), str(owner_item)) == ("Living room", "Boiler")


class TestScreens:
    def test_stable_addresses(self, alice_home: Home, owner_room: Room, owner_item: Item) -> None:
        assert url("detail", alice_home, room_id=owner_room.id) == (
            f"/h/{alice_home.id}/rooms/{owner_room.id}/"
        )
        assert url("item-detail", alice_home, item_id=owner_item.id) == (
            f"/h/{alice_home.id}/items/{owner_item.id}/"
        )

    def test_sign_in_is_required(self, client: Client, alice_home: Home, owner_room: Room) -> None:
        for address in (
            url("list", alice_home),
            url("detail", alice_home, room_id=owner_room.id),
            reverse("rooms"),
        ):
            response = client.get(address)
            assert response.status_code == 302
            assert reverse("account_login") in response["Location"]

    def test_list_and_detail(
        self, signed_in: Client, alice_home: Home, owner_room: Room, owner_item: Item
    ) -> None:
        listing = signed_in.get(url("list", alice_home))
        assert "Living room" in listing.text
        assert "1 item" in listing.text
        detail = signed_in.get(url("detail", alice_home, room_id=owner_room.id))
        assert "Boiler" in detail.text
        assert "Nothing noted yet" in detail.text

    def test_empty_list(self, signed_in: Client, alice_home: Home) -> None:
        assert "No room yet." in signed_in.get(url("list", alice_home)).text

    def test_create_a_room_with_the_name_only(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.post(url("create", alice_home), {"name": "Hall", "kind": "hallway"})
        room = Room.objects.get(name="Hall")
        assert response.status_code == 302
        assert response["Location"] == url("detail", alice_home, room_id=room.id)
        assert signed_in.get(url("create", alice_home)).status_code == 200

    def test_a_room_without_a_name_is_refused(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.post(url("create", alice_home), {"name": "", "kind": "other"})
        assert response.status_code == 200
        assert not Room.objects.exists()

    def test_edit_memory_and_delete(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        kwargs = {"room_id": owner_room.id}
        assert signed_in.get(url("edit", alice_home, **kwargs)).status_code == 200
        signed_in.post(url("edit", alice_home, **kwargs), {"name": "Lounge", "kind": "living"})
        assert signed_in.get(url("memory", alice_home, **kwargs)).status_code == 200
        signed_in.post(
            url("memory", alice_home, **kwargs), {"paint_brand": "Acme", "memory_notes": "1 tin"}
        )
        owner_room.refresh_from_db()
        assert (owner_room.name, owner_room.paint_brand) == ("Lounge", "Acme")
        detail = signed_in.get(url("detail", alice_home, **kwargs))
        assert "Acme" in detail.text
        assert "Delete" in signed_in.get(url("delete", alice_home, **kwargs)).text
        assert Room.objects.filter(id=owner_room.id).exists()
        assert signed_in.post(url("delete", alice_home, **kwargs)).status_code == 302
        assert not Room.objects.filter(id=owner_room.id).exists()

    def test_reorder_screen(self, signed_in: Client, alice: User, alice_home: Home) -> None:
        a = services.create_room(alice, alice_home, name="a")
        b = services.create_room(alice, alice_home, name="b")
        page = signed_in.get(url("list", alice_home) + "?reorder=1")
        assert 'name="direction"' in page.text
        response = signed_in.post(url("move", alice_home, room_id=b.id), {"direction": "up"})
        assert response["Location"].endswith("?reorder=1")
        assert [r.name for r in services.rooms_of(alice_home)] == ["b", "a"]
        signed_in.post(url("move", alice_home, room_id=a.id), {"direction": "nonsense"})
        assert signed_in.get(url("move", alice_home, room_id=a.id)).status_code == 405

    def test_items(self, signed_in: Client, alice_home: Home, owner_room: Room) -> None:
        kitchen_id = owner_room.id
        form = url("item-create", alice_home, room_id=kitchen_id)
        assert signed_in.get(form).status_code == 200
        response = signed_in.post(
            form,
            {
                "room": kitchen_id,
                "name": "Stove",
                "kind": "equipment",
                "installed_on": "2021-09-14",
                "warranty_ends_on": "2020-01-01",
                "contract_url": "https://example.com/c",
                "links": "https://example.com/manual Manual",
            },
        )
        item = Item.objects.get(name="Stove")
        assert response["Location"] == url("item-detail", alice_home, item_id=item.id)
        page = signed_in.get(response["Location"])
        assert "ended on" in page.text
        assert 'rel="noopener noreferrer nofollow"' in page.text
        assert item.links == [{"url": "https://example.com/manual", "label": "Manual"}]

    def test_bad_links_are_refused(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        response = signed_in.post(
            url("item-create", alice_home, room_id=owner_room.id),
            {
                "room": owner_room.id,
                "name": "x",
                "kind": "equipment",
                "links": "javascript:alert(1)",
            },
        )
        assert response.status_code == 200
        assert not Item.objects.exists()

    def test_edit_moves_and_delete_an_item(
        self, signed_in: Client, alice: User, alice_home: Home, owner_item: Item
    ) -> None:
        kitchen = services.create_room(alice, alice_home, name="Kitchen")
        edit = url("item-edit", alice_home, item_id=owner_item.id)
        assert "Boiler" in signed_in.get(edit).text
        signed_in.post(edit, {"room": kitchen.id, "name": "Oven", "kind": "equipment"})
        owner_item.refresh_from_db()
        assert (owner_item.room_id, owner_item.name) == (kitchen.id, "Oven")
        delete = url("item-delete", alice_home, item_id=owner_item.id)
        assert signed_in.get(delete).status_code == 200
        response = signed_in.post(delete)
        assert response["Location"] == url("detail", alice_home, room_id=kitchen.id)
        assert not Item.objects.exists()

    def test_the_item_form_offers_only_the_rooms_of_the_home(
        self, signed_in: Client, bob: User, bob_home: Home, alice_home: Home, owner_item: Item
    ) -> None:
        theirs = services.create_room(bob, bob_home, name="Their cellar")
        edit = url("item-edit", alice_home, item_id=owner_item.id)
        assert "Their cellar" not in signed_in.get(edit).text
        response = signed_in.post(edit, {"room": theirs.id, "name": "x", "kind": "equipment"})
        assert response.status_code == 200
        owner_item.refresh_from_db()
        assert owner_item.name == "Boiler"

    def test_search(self, signed_in: Client, alice_home: Home, owner_item: Item) -> None:
        page = signed_in.get(url("search", alice_home), {"q": "boil"})
        assert "Boiler" in page.text
        assert "Nothing matches" in signed_in.get(url("search", alice_home), {"q": "zzz"}).text
        assert signed_in.get(url("search", alice_home)).status_code == 200

    def test_entry_goes_to_the_only_home(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.get(reverse("rooms"))
        assert response["Location"] == url("list", alice_home)

    def test_entry_opens_the_current_home_among_several(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        from housecairn.homes import services as home_services

        flat = home_services.create_home(alice, name="Holiday flat")
        # No choice yet: the first home by name, never a page that asks.
        page = signed_in.get(reverse("rooms"))
        assert page["Location"] == reverse("rooms:list", kwargs={"home_id": flat.id})

    def test_entry_without_a_home(self, signed_in: Client) -> None:
        assert "no home to open" in signed_in.get(reverse("rooms")).text

    def test_navigation_leads_to_the_rooms_of_the_home_in_view(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        page = signed_in.get(reverse("homes:detail", kwargs={"home_id": alice_home.id}))
        assert f'href="{url("list", alice_home)}"' in page.text
        elsewhere = signed_in.get(reverse("more"))
        assert f'href="{reverse("rooms")}"' in elsewhere.text


class TestIsolationAndRoles:
    """A stranger, the instance administrator and a read-only member, on the web."""

    def addresses(self, home: Home, room: Room, item: Item) -> list[str]:
        return [
            url("list", home),
            url("create", home),
            url("detail", home, room_id=room.id),
            url("edit", home, room_id=room.id),
            url("memory", home, room_id=room.id),
            url("delete", home, room_id=room.id),
            url("item-create", home, room_id=room.id),
            url("item-detail", home, item_id=item.id),
            url("item-edit", home, item_id=item.id),
            url("item-delete", home, item_id=item.id),
            url("room-photo-add", home, room_id=room.id),
            url("item-photo-add", home, item_id=item.id),
            url("search", home),
        ]

    @pytest.mark.parametrize("who", ["bob", "site_admin"])
    def test_a_stranger_gets_404_everywhere(
        self,
        request: pytest.FixtureRequest,
        client: Client,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        who: str,
    ) -> None:
        client.force_login(request.getfixturevalue(who))
        for address in self.addresses(alice_home, owner_room, owner_item):
            assert client.get(address).status_code == 404, address
        for address in (url("move", alice_home, room_id=owner_room.id),):
            assert client.post(address, {"direction": "up"}).status_code == 404
        assert Room.objects.filter(id=owner_room.id).exists()

    @pytest.mark.parametrize("who", ["bob", "site_admin"])
    def test_a_stranger_cannot_write_by_post(
        self,
        request: pytest.FixtureRequest,
        client: Client,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        who: str,
    ) -> None:
        """Not a member (nor the instance administrator): 404 and nothing changes."""
        client.force_login(request.getfixturevalue(who))
        photo = upload(image_bytes())
        attempts = [
            (url("edit", alice_home, room_id=owner_room.id), {"name": "Hacked"}),
            (url("memory", alice_home, room_id=owner_room.id), {"notes": "Hacked"}),
            (url("delete", alice_home, room_id=owner_room.id), {}),
            (url("item-edit", alice_home, item_id=owner_item.id), {"name": "Hacked"}),
            (url("item-delete", alice_home, item_id=owner_item.id), {}),
            (url("room-photo-add", alice_home, room_id=owner_room.id), {"file": photo}),
            (url("item-photo-add", alice_home, item_id=owner_item.id), {"file": photo}),
        ]
        for address, data in attempts:
            assert client.post(address, data).status_code == 404, address
        assert Room.objects.get(id=owner_room.id).name == "Living room"
        assert Item.objects.get(id=owner_item.id).name == "Boiler"
        assert not Photo.objects.exists()

    def test_unknown_and_foreign_identifiers_answer_the_same_404(
        self, signed_in: Client, bob: User, alice_home: Home, bob_home: Home
    ) -> None:
        theirs = services.create_room(bob, bob_home, name="Their room")
        foreign = signed_in.get(url("detail", alice_home, room_id=theirs.id))
        unknown = signed_in.get(url("detail", alice_home, room_id=uuid.uuid4()))
        assert foreign.status_code == unknown.status_code == 404
        token = re.compile(rb"[A-Za-z0-9]{64}")  # the CSRF token differs on every page
        assert token.sub(b"", foreign.content) == token.sub(b"", unknown.content)
        assert signed_in.get(url("detail", bob_home, room_id=theirs.id)).status_code == 404

    def test_read_only_reads_but_cannot_write(
        self,
        client: Client,
        reader: User,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
    ) -> None:
        client.force_login(reader)
        writing = {
            url("create", alice_home),
            url("edit", alice_home, room_id=owner_room.id),
            url("memory", alice_home, room_id=owner_room.id),
            url("delete", alice_home, room_id=owner_room.id),
            url("item-create", alice_home, room_id=owner_room.id),
            url("item-edit", alice_home, item_id=owner_item.id),
            url("item-delete", alice_home, item_id=owner_item.id),
            url("room-photo-add", alice_home, room_id=owner_room.id),
            url("item-photo-add", alice_home, item_id=owner_item.id),
        }
        for address in self.addresses(alice_home, owner_room, owner_item):
            expected = 403 if address in writing else 200
            assert client.get(address).status_code == expected, address
        for address in (*writing, url("move", alice_home, room_id=owner_room.id)):
            assert client.post(address, {"name": "x", "direction": "up"}).status_code == 403, (
                address
            )
        page = client.get(url("detail", alice_home, room_id=owner_room.id))
        assert "Add an item" not in page.text
        assert "Edit the room" not in page.text
        assert Room.objects.get(id=owner_room.id).name == "Living room"

    def test_a_locked_home_asks_for_its_provider(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        Home.objects.filter(id=alice_home.id).update(required_provider="company-sso")
        response = signed_in.get(url("detail", alice_home, room_id=owner_room.id))
        assert response.status_code == 403
