"""API of rooms, items and photos: parity with the screens, scopes, roles, isolation."""

import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.rooms import conf, services
from housecairn.rooms.models import Item, Photo, Room
from tests.rooms_support import image_bytes, noise_image, upload

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]


def api(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"api-v1:home-{name}", kwargs={"home_id": home.id, **kwargs})


@pytest.fixture
def client_of_alice(api_client: APIClient, alice: User) -> APIClient:
    api_client.force_authenticate(alice)
    return api_client


class TestRooms:
    def test_crud(self, client_of_alice: APIClient, alice_home: Home) -> None:
        created = client_of_alice.post(
            api("room-list", alice_home), {"name": "Hall", "kind": "hallway", "paint_brand": "Acme"}
        )
        assert created.status_code == 201
        body = created.json()
        assert (body["name"], body["position"], body["item_count"]) == ("Hall", 0, 0)
        detail = api("room-detail", alice_home, room_id=body["id"])
        assert client_of_alice.get(detail).json()["paint_brand"] == "Acme"
        patched = client_of_alice.patch(detail, {"name": "Entrance"})
        assert patched.json()["name"] == "Entrance"
        assert client_of_alice.delete(detail).status_code == 204
        assert client_of_alice.get(detail).status_code == 404

    def test_only_the_name_is_required_and_position_is_not_writable(
        self, client_of_alice: APIClient, alice_home: Home
    ) -> None:
        assert client_of_alice.post(api("room-list", alice_home), {}).status_code == 400
        created = client_of_alice.post(api("room-list", alice_home), {"name": "x", "position": 9})
        assert created.json()["position"] == 0

    @pytest.mark.parametrize("name", [None, "", "  ", "\u200b\u200d", "\U000e0061\U000e0062"])
    def test_an_empty_or_invisible_name_takes_the_label_of_the_type(
        self, client_of_alice: APIClient, alice_home: Home, name: str | None
    ) -> None:
        data = {"kind": "kitchen"} if name is None else {"kind": "kitchen", "name": name}
        created = client_of_alice.post(api("room-list", alice_home), data)
        assert created.status_code == 201
        assert created.json()["name"] == "Kitchen"
        detail = api("room-detail", alice_home, room_id=created.json()["id"])
        renamed = client_of_alice.patch(detail, {"name": "Cooking"})
        assert renamed.json()["name"] == "Cooking"
        blanked = client_of_alice.patch(detail, {"name": name or ""})
        assert blanked.status_code == 200
        assert blanked.json()["name"] == "Kitchen"

    @pytest.mark.parametrize("name", [None, "", "\u200b"])
    def test_the_type_other_still_needs_a_visible_name(
        self, client_of_alice: APIClient, alice_home: Home, name: str | None
    ) -> None:
        data = {"kind": "other"} if name is None else {"kind": "other", "name": name}
        response = client_of_alice.post(api("room-list", alice_home), data)
        assert response.status_code == 400
        assert "name" in response.json()

    def test_validation_errors_are_reported_by_field(
        self, client_of_alice: APIClient, alice_home: Home
    ) -> None:
        response = client_of_alice.post(
            api("room-list", alice_home), {"name": "x", "notes": "n" * 4001}
        )
        assert response.status_code == 400
        assert "notes" in response.json()

    def test_listing_is_ordered_and_paginated_by_cursor(
        self, client_of_alice: APIClient, alice: User, alice_home: Home
    ) -> None:
        for name in ("a", "b", "c"):
            services.create_room(alice, alice_home, name=name)
        first = client_of_alice.get(api("room-list", alice_home), {"page_size": 2}).json()
        assert [r["name"] for r in first["results"]] == ["a", "b"]
        assert first["next"]
        second = client_of_alice.get(first["next"]).json()
        assert [r["name"] for r in second["results"]] == ["c"]
        assert second["next"] is None

    def test_filter_by_name(
        self, client_of_alice: APIClient, alice: User, alice_home: Home
    ) -> None:
        services.create_room(alice, alice_home, name="Kitchen")
        services.create_room(alice, alice_home, name="Garage")
        names = [
            r["name"]
            for r in client_of_alice.get(api("room-list", alice_home), {"q": "kit"}).json()[
                "results"
            ]
        ]
        assert names == ["Kitchen"]

    def test_reorder(self, client_of_alice: APIClient, alice: User, alice_home: Home) -> None:
        _a, b, c = (services.create_room(alice, alice_home, name=n) for n in "abc")
        response = client_of_alice.post(
            api("room-reorder", alice_home), {"order": [str(c.id), str(b.id)]}
        )
        assert [r["name"] for r in response.json()] == ["c", "b", "a"]
        bad = client_of_alice.post(api("room-reorder", alice_home), {"order": [str(uuid.uuid4())]})
        assert bad.status_code == 400
        assert (
            client_of_alice.post(api("room-reorder", alice_home), {"order": "nope"}).status_code
            == 400
        )
        assert client_of_alice.post(api("room-reorder", alice_home), {}).status_code == 400

    def test_methods_not_offered(
        self, client_of_alice: APIClient, alice_home: Home, owner_room: Room
    ) -> None:
        detail = api("room-detail", alice_home, room_id=owner_room.id)
        assert client_of_alice.put(detail, {"name": "x"}).status_code == 405


class TestItems:
    def test_crud_and_move(
        self, client_of_alice: APIClient, alice: User, alice_home: Home, owner_room: Room
    ) -> None:
        kitchen = services.create_room(alice, alice_home, name="Kitchen")
        created = client_of_alice.post(
            api("item-list", alice_home),
            {
                "room": str(owner_room.id),
                "name": "Stove",
                "brand": "Acme",
                "installed_on": "2021-09-14",
                "links": [{"url": "https://example.com/manual", "label": "Manual"}],
            },
        )
        assert created.status_code == 201, created.json()
        body = created.json()
        assert body["room"] == str(owner_room.id)
        assert body["links"] == [{"url": "https://example.com/manual", "label": "Manual"}]
        detail = api("item-detail", alice_home, item_id=body["id"])
        moved = client_of_alice.patch(detail, {"room": str(kitchen.id)})
        assert moved.json()["room"] == str(kitchen.id)
        assert (
            client_of_alice.patch(detail, {"serial_number": "SN1"}).json()["serial_number"] == "SN1"
        )
        assert client_of_alice.delete(detail).status_code == 204
        assert client_of_alice.get(detail).status_code == 404

    def test_bad_values_are_refused(
        self, client_of_alice: APIClient, alice_home: Home, owner_room: Room
    ) -> None:
        listing = api("item-list", alice_home)
        base = {"room": str(owner_room.id), "name": "x"}
        assert client_of_alice.post(listing, {"name": "x"}).status_code == 400
        for extra in (
            {"contract_url": "javascript:alert(1)"},
            {"links": [{"url": "javascript:alert(1)"}]},
            {"links": [{"url": "https://example.com"}] * 11},
        ):
            assert client_of_alice.post(listing, {**base, **extra}).status_code == 400, extra

    def test_a_room_of_another_home_is_unknown(
        self,
        client_of_alice: APIClient,
        bob: User,
        bob_home: Home,
        alice_home: Home,
        owner_item: Item,
    ) -> None:
        theirs = services.create_room(bob, bob_home, name="theirs")
        unknown = client_of_alice.post(
            api("item-list", alice_home), {"room": str(uuid.uuid4()), "name": "x"}
        )
        foreign = client_of_alice.post(
            api("item-list", alice_home), {"room": str(theirs.id), "name": "x"}
        )
        assert unknown.status_code == foreign.status_code == 400
        assert unknown.json().keys() == foreign.json().keys() == {"room"}
        detail = api("item-detail", alice_home, item_id=owner_item.id)
        assert client_of_alice.patch(detail, {"room": str(theirs.id)}).status_code == 400

    def test_filters(
        self,
        client_of_alice: APIClient,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
    ) -> None:
        other = services.create_room(alice, alice_home, name="Cellar")
        services.create_item(alice, other, name="Shelf")
        listing = api("item-list", alice_home)
        in_room = client_of_alice.get(listing, {"room": str(owner_room.id)}).json()["results"]
        assert [i["name"] for i in in_room] == ["Boiler"]
        by_name = client_of_alice.get(listing, {"q": "shel"}).json()["results"]
        assert [i["name"] for i in by_name] == ["Shelf"]
        assert client_of_alice.get(listing, {"room": "not-a-uuid"}).status_code == 400

    def test_search(
        self, client_of_alice: APIClient, alice_home: Home, owner_room: Room, owner_item: Item
    ) -> None:
        body = client_of_alice.get(api("search", alice_home), {"q": "boil"}).json()
        assert [i["name"] for i in body["items"]] == ["Boiler"]
        assert body["rooms"] == []
        empty = client_of_alice.get(api("search", alice_home)).json()
        assert empty == {"rooms": [], "items": []}


class TestPhotos:
    def post(self, client: APIClient, home: Home, data: bytes, **fields: object) -> object:
        return client.post(
            api("photo-list", home),
            {"file": upload(data), **fields},
            format="multipart",
        )

    def test_upload_read_update_delete(
        self, client_of_alice: APIClient, alice_home: Home, owner_room: Room
    ) -> None:
        response = self.post(
            client_of_alice,
            alice_home,
            image_bytes("JPEG", gps=True),
            room=str(owner_room.id),
            caption="North wall",
            category="behind_walls",
        )
        assert response.status_code == 201, response.json()  # type: ignore[attr-defined]
        body = response.json()  # type: ignore[attr-defined]
        assert (body["content_type"], body["category"], body["room"], body["item"]) == (
            "image/jpeg",
            "behind_walls",
            str(owner_room.id),
            None,
        )
        detail = api("photo-detail", alice_home, photo_id=body["id"])
        assert client_of_alice.get(detail).json()["caption"] == "North wall"
        content = client_of_alice.get(body["content_url"])
        assert content.status_code == 200
        assert content["Content-Type"] == "image/jpeg"
        assert content["X-Content-Type-Options"] == "nosniff"
        assert content["Content-Disposition"].startswith("inline")
        thumbnail = client_of_alice.get(body["thumbnail_url"])
        assert thumbnail["Content-Type"] == "image/jpeg"
        patched = client_of_alice.patch(detail, {"caption": "Cables", "width": 1})
        assert patched.json()["caption"] == "Cables"
        assert patched.json()["width"] == body["width"]
        assert client_of_alice.delete(detail).status_code == 204
        assert client_of_alice.get(detail).status_code == 404
        assert client_of_alice.get(body["content_url"]).status_code == 404

    def test_the_image_is_served_whatever_accept_asks(
        self, client_of_alice: APIClient, alice: User, owner_room: Room, alice_home: Home
    ) -> None:
        photo = services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))
        address = api("photo-content", alice_home, photo_id=photo.id)
        assert client_of_alice.get(address, HTTP_ACCEPT="image/png").status_code == 200

    def test_upload_to_an_item_and_filters(
        self,
        client_of_alice: APIClient,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
    ) -> None:
        self.post(client_of_alice, alice_home, image_bytes(), item=str(owner_item.id))
        services.add_photo(
            alice, room=owner_room, upload=upload(image_bytes()), category="behind_walls"
        )
        listing = api("photo-list", alice_home)
        assert len(client_of_alice.get(listing).json()["results"]) == 2
        of_item = client_of_alice.get(listing, {"item": str(owner_item.id)}).json()["results"]
        assert len(of_item) == 1
        of_room = client_of_alice.get(listing, {"room": str(owner_room.id)}).json()["results"]
        assert len(of_room) == 1
        walls = client_of_alice.get(listing, {"category": "behind_walls"}).json()["results"]
        assert len(walls) == 1

    def test_bad_uploads(
        self, client_of_alice: APIClient, alice_home: Home, owner_room: Room, owner_item: Item
    ) -> None:
        room = str(owner_room.id)
        fake = self.post(client_of_alice, alice_home, b"text, not an image", room=room)
        assert fake.status_code == 400  # type: ignore[attr-defined]
        assert "not a valid" in str(fake.json())  # type: ignore[attr-defined]
        neither = self.post(client_of_alice, alice_home, image_bytes())
        both = self.post(
            client_of_alice, alice_home, image_bytes(), room=room, item=str(owner_item.id)
        )
        assert neither.status_code == both.status_code == 400  # type: ignore[attr-defined]
        data = noise_image("PNG")
        with override_settings(HOUSECAIRN_PHOTO_MAX_BYTES=len(data) - 1):
            big = self.post(client_of_alice, alice_home, data, room=room)
        assert big.status_code == 400  # type: ignore[attr-defined]
        assert "limit" in str(big.json())  # type: ignore[attr-defined]
        missing = client_of_alice.post(
            api("photo-list", alice_home), {"room": room}, format="multipart"
        )
        assert missing.status_code == 400
        assert (
            client_of_alice.post(
                api("photo-list", alice_home), {"room": room}, format="json"
            ).status_code
            == 400
        )
        assert Photo.objects.count() == 0

    def test_an_unknown_target_is_a_404(self, client_of_alice: APIClient, alice_home: Home) -> None:
        assert (
            self.post(
                client_of_alice, alice_home, image_bytes(), room=str(uuid.uuid4())
            ).status_code
            == 404
        )  # type: ignore[attr-defined]
        assert (
            self.post(
                client_of_alice, alice_home, image_bytes(), item=str(uuid.uuid4())
            ).status_code
            == 404
        )  # type: ignore[attr-defined]

    def test_an_oversized_body_is_refused_before_it_is_read(
        self, client_of_alice: APIClient, alice_home: Home, owner_room: Room
    ) -> None:
        with override_settings(HOUSECAIRN_PHOTO_MAX_BYTES=10_240):
            response = client_of_alice.post(
                api("photo-list", alice_home),
                data=b"x",
                content_type="multipart/form-data; boundary=x",
                headers={"Content-Length": str(10_240 + conf.MULTIPART_OVERHEAD + 1)},
            )
        assert response.status_code == 413


class TestRolesScopesAndIsolation:
    def endpoints(self, home: Home, room: Room, item: Item, photo: Photo) -> list[tuple[str, str]]:
        return [
            ("get", api("room-list", home)),
            ("get", api("room-detail", home, room_id=room.id)),
            ("get", api("item-list", home)),
            ("get", api("item-detail", home, item_id=item.id)),
            ("get", api("photo-list", home)),
            ("get", api("photo-detail", home, photo_id=photo.id)),
            ("get", api("photo-content", home, photo_id=photo.id)),
            ("get", api("photo-thumbnail", home, photo_id=photo.id)),
            ("get", api("search", home) + "?q=a"),
        ]

    def writes(
        self, home: Home, room: Room, item: Item, photo: Photo
    ) -> list[tuple[str, str, dict[str, object]]]:
        return [
            ("post", api("room-list", home), {"name": "x"}),
            ("patch", api("room-detail", home, room_id=room.id), {"name": "x"}),
            ("delete", api("room-detail", home, room_id=room.id), {}),
            ("post", api("room-reorder", home), {"order": [str(room.id)]}),
            ("post", api("item-list", home), {"room": str(room.id), "name": "x"}),
            ("patch", api("item-detail", home, item_id=item.id), {"name": "x"}),
            ("delete", api("item-detail", home, item_id=item.id), {}),
            (
                "post",
                api("photo-list", home),
                {"room": str(room.id), "file": upload(image_bytes())},
            ),
            ("patch", api("photo-detail", home, photo_id=photo.id), {"caption": "x"}),
            ("delete", api("photo-detail", home, photo_id=photo.id), {}),
        ]

    @pytest.fixture
    def photo(self, alice: User, owner_room: Room) -> Photo:
        return services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))

    @pytest.mark.parametrize("who", ["bob", "site_admin"])
    def test_a_stranger_sees_and_changes_nothing(
        self,
        request: pytest.FixtureRequest,
        api_client: APIClient,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        photo: Photo,
        who: str,
    ) -> None:
        api_client.force_authenticate(request.getfixturevalue(who))
        for method, address in self.endpoints(alice_home, owner_room, owner_item, photo):
            assert getattr(api_client, method)(address).status_code == 404, address
        for method, address, data in self.writes(alice_home, owner_room, owner_item, photo):
            response = getattr(api_client, method)(
                address, data, format="multipart" if "file" in data else "json"
            )
            assert response.status_code == 404, (method, address)
        assert Room.objects.filter(id=owner_room.id).exists()
        assert Photo.objects.filter(id=photo.id).exists()

    def test_a_member_of_home_b_cannot_use_the_identifiers_of_home_a(
        self,
        api_client: APIClient,
        bob: User,
        bob_home: Home,
        owner_room: Room,
        owner_item: Item,
        photo: Photo,
    ) -> None:
        """Right user, wrong home: the identifiers of A through B's address are unknown."""
        api_client.force_authenticate(bob)
        for address in (
            api("room-detail", bob_home, room_id=owner_room.id),
            api("item-detail", bob_home, item_id=owner_item.id),
            api("photo-detail", bob_home, photo_id=photo.id),
            api("photo-content", bob_home, photo_id=photo.id),
            api("photo-thumbnail", bob_home, photo_id=photo.id),
        ):
            assert api_client.get(address).status_code == 404, address
        assert api_client.get(api("room-list", bob_home)).json()["results"] == []

    def test_read_only_reads_everything_and_changes_nothing(
        self,
        api_client: APIClient,
        reader: User,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        photo: Photo,
    ) -> None:
        api_client.force_authenticate(reader)
        for method, address in self.endpoints(alice_home, owner_room, owner_item, photo):
            assert getattr(api_client, method)(address).status_code == 200, address
        for method, address, data in self.writes(alice_home, owner_room, owner_item, photo):
            response = getattr(api_client, method)(
                address, data, format="multipart" if "file" in data else "json"
            )
            assert response.status_code == 403, (method, address)
        assert Room.objects.get(id=owner_room.id).name == "Living room"

    def test_a_member_writes(self, api_client: APIClient, member: User, alice_home: Home) -> None:
        api_client.force_authenticate(member)
        assert api_client.post(api("room-list", alice_home), {"name": "x"}).status_code == 201

    @pytest.fixture
    def token(self, alice: User, alice_home: Home) -> Callable[..., APIClient]:
        def make(scopes: list[str], homes: list[Home] | None = None) -> APIClient:
            _token, raw = token_services.issue_token(
                alice,
                name="t",
                scopes=scopes,
                homes=homes or [alice_home],
                lifetime=timedelta(days=1),
            )
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
            return client

        return make

    def test_scopes_of_a_token(
        self,
        token: Callable[..., APIClient],
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        photo: Photo,
    ) -> None:
        reading = token(["read"])
        for method, address in self.endpoints(alice_home, owner_room, owner_item, photo):
            assert getattr(reading, method)(address).status_code == 200, address
        for method, address, data in self.writes(alice_home, owner_room, owner_item, photo):
            response = getattr(reading, method)(
                address, data, format="multipart" if "file" in data else "json"
            )
            assert response.status_code == 403, (method, address)
        writing = token(["write"])
        assert writing.post(api("room-list", alice_home), {"name": "x"}).status_code == 201
        assert writing.get(api("room-list", alice_home)).status_code == 403
        events_only = token(["events"])
        assert events_only.get(api("room-list", alice_home)).status_code == 403
        assert events_only.post(api("room-list", alice_home), {"name": "y"}).status_code == 403

    def test_a_token_bound_to_another_home_sees_nothing(
        self,
        token: Callable[..., APIClient],
        alice: User,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        photo: Photo,
    ) -> None:
        second = home_services.create_home(alice, name="Holiday flat")
        client = token(["read", "write"], [second])
        for method, address in self.endpoints(alice_home, owner_room, owner_item, photo):
            assert getattr(client, method)(address).status_code == 404, address
        for method, address, data in self.writes(alice_home, owner_room, owner_item, photo):
            response = getattr(client, method)(
                address, data, format="multipart" if "file" in data else "json"
            )
            assert response.status_code == 404, (method, address)
        assert client.get(api("room-list", second)).status_code == 200

    def test_anonymous_requests_are_refused(
        self, alice_home: Home, owner_room: Room, owner_item: Item, photo: Photo
    ) -> None:
        anonymous = APIClient()
        for method, address in self.endpoints(alice_home, owner_room, owner_item, photo):
            assert getattr(anonymous, method)(address).status_code in {401, 403}, address

    def test_anonymous_writes_are_refused_and_change_nothing(
        self, alice_home: Home, owner_room: Room, owner_item: Item, photo: Photo
    ) -> None:
        anonymous = APIClient()
        for method, address, data in self.writes(alice_home, owner_room, owner_item, photo):
            response = getattr(anonymous, method)(
                address, data, format="multipart" if "file" in data else "json"
            )
            assert response.status_code in {401, 403}, (method, address)
        assert Room.objects.get(id=owner_room.id).name == "Living room"
        assert Item.objects.get(id=owner_item.id).name == "Boiler"
        assert Photo.objects.count() == 1
        assert Photo.objects.get(id=photo.id).caption == ""

    def test_unknown_and_foreign_identifiers_answer_the_same_404_body(
        self,
        client_of_alice: APIClient,
        bob: User,
        alice_home: Home,
        bob_home: Home,
    ) -> None:
        """Byte for byte: nothing tells an unknown identifier from one of another home."""
        theirs_room = services.create_room(bob, bob_home, name="Their room")
        theirs_item = services.create_item(bob, theirs_room, name="Their item")
        theirs_photo = services.add_photo(bob, room=theirs_room, upload=upload(image_bytes()))
        pairs = [
            ("room-detail", "room_id", theirs_room.id),
            ("item-detail", "item_id", theirs_item.id),
            ("photo-detail", "photo_id", theirs_photo.id),
            ("photo-content", "photo_id", theirs_photo.id),
            ("photo-thumbnail", "photo_id", theirs_photo.id),
        ]
        for name, key, foreign_id in pairs:
            foreign = client_of_alice.get(api(name, alice_home, **{key: foreign_id}))
            unknown = client_of_alice.get(api(name, alice_home, **{key: uuid.uuid4()}))
            assert foreign.status_code == unknown.status_code == 404, name
            assert foreign.content == unknown.content, name
            assert foreign["Content-Type"] == unknown["Content-Type"], name
