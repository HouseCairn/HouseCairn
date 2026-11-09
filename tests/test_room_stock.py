"""Stock of a room: the articles that concern it, and the paint left over as a link (ADR 0046)."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.rooms import services as room_services
from housecairn.rooms.models import Item, Room
from housecairn.stock import services
from housecairn.stock.models import Article

pytest_plugins = ("tests.rooms_fixtures", "tests.stock_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]

D = Decimal


def room_url(name: str, home: Home, room: Room) -> str:
    return reverse(f"rooms:{name}", kwargs={"home_id": home.id, "room_id": room.id})


def api(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"api-v1:home-{name}", kwargs={"home_id": home.id, **kwargs})


@pytest.fixture
def hall(alice: User, alice_home: Home) -> Room:
    return room_services.create_room(alice, alice_home, name="Hall")


@pytest.fixture
def tin(alice: User, alice_home: Home) -> Article:
    item = services.create_article(
        alice, alice_home, name="Sage paint", unit="litre", storage_location="Garage, top shelf"
    )
    services.record_movement(alice, item, kind="entry", quantity=D("2.5"))
    return item


def names(rows: object) -> list[str]:
    return sorted(a.name for a in rows)  # type: ignore[attr-defined]


class TestArticlesOfARoom:
    def test_three_ways_to_concern_a_room(
        self,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        hall: Room,
        tin: Article,
    ) -> None:
        services.create_article(alice, alice_home, name="By item", compatible_items=[owner_item])
        services.create_article(alice, alice_home, name="By room", rooms=[owner_room])
        services.create_article(alice, alice_home, name="Elsewhere", rooms=[hall])
        services.create_article(alice, alice_home, name="Nowhere")
        room_services.update_room(alice, owner_room, paint_article=tin)
        found = services.articles_of_room(alice_home, owner_room.id)
        assert names(found) == ["By item", "By room", "Sage paint"]

    def test_an_article_fitting_two_items_of_the_room_appears_once(
        self, alice: User, alice_home: Home, owner_room: Room, owner_item: Item
    ) -> None:
        second = room_services.create_item(alice, owner_room, name="Pump")
        services.create_article(
            alice,
            alice_home,
            name="Seal",
            compatible_items=[owner_item, second],
            rooms=[owner_room],
        )
        assert names(services.articles_of_room(alice_home, owner_room.id)) == ["Seal"]

    def test_a_deleted_item_does_not_bring_its_articles(
        self, alice: User, alice_home: Home, owner_room: Room, owner_item: Item
    ) -> None:
        services.create_article(alice, alice_home, name="Seal", compatible_items=[owner_item])
        room_services.delete_item(alice, owner_item)
        assert names(services.articles_of_room(alice_home, owner_room.id)) == []

    def test_a_deleted_article_drops_out(
        self, alice: User, alice_home: Home, owner_room: Room, tin: Article
    ) -> None:
        services.update_article(alice, tin, rooms=[owner_room])
        services.delete_article(alice, tin)
        assert names(services.articles_of_room(alice_home, owner_room.id)) == []

    def test_the_room_must_be_in_the_home(
        self, alice: User, alice_home: Home, bob: User, bob_home: Home, tin: Article
    ) -> None:
        elsewhere = room_services.create_room(bob, bob_home, name="Elsewhere")
        with pytest.raises(ValidationError) as caught:
            services.update_article(alice, tin, rooms=[elsewhere])
        assert "rooms" in caught.value.message_dict
        with pytest.raises(ValidationError):
            services.create_article(alice, alice_home, name="x", rooms=[elsewhere])
        assert list(tin.rooms.all()) == []

    def test_the_search_filters_by_room(
        self, alice: User, alice_home: Home, owner_room: Room, hall: Room
    ) -> None:
        services.create_article(alice, alice_home, name="Hall tape", rooms=[hall])
        services.create_article(alice, alice_home, name="Hall lamp", rooms=[hall, owner_room])
        found = services.search_articles(alice_home, "lamp", room=hall.id)
        assert names(found) == ["Hall lamp"]
        assert names(services.search_articles(alice_home, room=owner_room.id)) == ["Hall lamp"]


class TestRoomPage:
    def test_it_lists_the_articles_with_quantity_and_place(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        tin: Article,
    ) -> None:
        services.update_article(alice, tin, rooms=[owner_room])
        page = signed_in.get(room_url("detail", alice_home, owner_room))
        assert "Sage paint" in page.text
        assert "2.5" in page.text
        assert "Garage, top shelf" in page.text

    def test_it_says_when_there_is_none(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        page = signed_in.get(room_url("detail", alice_home, owner_room))
        assert "No stock item for this room yet." in page.text

    def test_it_flags_a_low_article(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room, tin: Article
    ) -> None:
        services.update_article(alice, tin, rooms=[owner_room], threshold=D("5"))
        page = signed_in.get(room_url("detail", alice_home, owner_room))
        assert "Low stock" in page.text

    def test_a_reader_sees_it(
        self,
        client: Client,
        reader: User,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        tin: Article,
    ) -> None:
        services.update_article(alice, tin, rooms=[owner_room])
        client.force_login(reader)
        assert "Sage paint" in client.get(room_url("detail", alice_home, owner_room)).text

    def test_the_article_form_chooses_rooms(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        response = signed_in.post(
            reverse("stock:create", kwargs={"home_id": alice_home.id}),
            {"name": "Tape", "rooms": [str(owner_room.id)]},
        )
        assert response.status_code == 302, response.text
        assert [r.id for r in Article.objects.get(name="Tape").rooms.all()] == [owner_room.id]

    def test_the_article_form_refuses_a_room_of_another_home(
        self, signed_in: Client, alice_home: Home, bob: User, bob_home: Home
    ) -> None:
        elsewhere = room_services.create_room(bob, bob_home, name="Elsewhere")
        response = signed_in.post(
            reverse("stock:create", kwargs={"home_id": alice_home.id}),
            {"name": "Tape", "rooms": [str(elsewhere.id)]},
        )
        assert response.status_code == 200
        assert not Article.objects.filter(name="Tape").exists()

    def test_the_article_page_lists_its_rooms(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room, tin: Article
    ) -> None:
        services.update_article(alice, tin, rooms=[owner_room])
        page = signed_in.get(
            reverse("stock:detail", kwargs={"home_id": alice_home.id, "article_id": tin.id})
        )
        assert "Living room" in page.text


class TestPaintLeftOver:
    def test_the_memory_links_a_stock_item_and_the_page_shows_its_quantity_and_place(
        self, signed_in: Client, alice_home: Home, owner_room: Room, tin: Article
    ) -> None:
        response = signed_in.post(
            room_url("memory", alice_home, owner_room),
            {"paint_colour": "Sage", "paint_article": str(tin.id)},
        )
        assert response.status_code == 302, response.text
        owner_room.refresh_from_db()
        assert owner_room.paint_article_id == tin.id
        page = signed_in.get(room_url("detail", alice_home, owner_room))
        assert "Paint left in stock" in page.text
        assert "Sage paint" in page.text
        assert "2.50 litre" in page.text
        assert "Garage, top shelf" in page.text

    def test_the_quantity_follows_the_stock(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room, tin: Article
    ) -> None:
        room_services.update_room(alice, owner_room, paint_article=tin)
        services.record_movement(alice, tin, kind="exit", quantity=D("1"))
        assert "1.50 litre" in signed_in.get(room_url("detail", alice_home, owner_room)).text

    def test_the_choice_is_the_articles_of_the_home_only(
        self, signed_in: Client, alice_home: Home, owner_room: Room, foreign_article: Article
    ) -> None:
        response = signed_in.post(
            room_url("memory", alice_home, owner_room), {"paint_article": str(foreign_article.id)}
        )
        assert response.status_code == 200
        owner_room.refresh_from_db()
        assert owner_room.paint_article_id is None

    def test_the_service_refuses_an_article_of_another_home(
        self, alice: User, owner_room: Room, foreign_article: Article
    ) -> None:
        with pytest.raises(ValidationError) as caught:
            room_services.update_room(alice, owner_room, paint_article=foreign_article)
        assert "paint_article" in caught.value.message_dict

    def test_a_reader_changes_nothing(
        self, client: Client, reader: User, alice_home: Home, owner_room: Room, tin: Article
    ) -> None:
        client.force_login(reader)
        response = client.post(
            room_url("memory", alice_home, owner_room), {"paint_article": str(tin.id)}
        )
        assert response.status_code == 403
        with pytest.raises(PermissionDenied):
            room_services.update_room(reader, owner_room, paint_article=tin)
        owner_room.refresh_from_db()
        assert owner_room.paint_article_id is None

    def test_a_deleted_article_is_no_longer_shown_and_the_room_still_saves(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room, tin: Article
    ) -> None:
        room_services.update_room(alice, owner_room, paint_article=tin)
        services.delete_article(alice, tin)
        assert "Sage paint" not in signed_in.get(room_url("detail", alice_home, owner_room)).text
        room_services.update_room(alice, owner_room, name="Lounge")
        owner_room.refresh_from_db()
        assert owner_room.name == "Lounge"

    def test_the_memory_can_be_cleared(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room, tin: Article
    ) -> None:
        room_services.update_room(alice, owner_room, paint_article=tin)
        signed_in.post(room_url("memory", alice_home, owner_room), {"paint_article": ""})
        owner_room.refresh_from_db()
        assert owner_room.paint_article_id is None


class TestApi:
    @pytest.fixture
    def client_of_alice(self, api_client: APIClient, alice: User) -> APIClient:
        api_client.force_authenticate(alice)
        return api_client

    def test_the_room_carries_its_paint_article(
        self, client_of_alice: APIClient, alice_home: Home, owner_room: Room, tin: Article
    ) -> None:
        detail = api("room-detail", alice_home, room_id=owner_room.id)
        patched = client_of_alice.patch(detail, {"paint_article": str(tin.id)}, format="json")
        assert patched.status_code == 200, patched.content
        assert (patched.json()["paint_article"], patched.json()["paint_article_name"]) == (
            str(tin.id),
            "Sage paint",
        )
        assert "paint_stock" not in patched.json()
        cleared = client_of_alice.patch(detail, {"paint_article": None}, format="json")
        assert cleared.json()["paint_article"] is None

    def test_another_home_s_article_is_a_400(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        owner_room: Room,
        foreign_article: Article,
    ) -> None:
        detail = api("room-detail", alice_home, room_id=owner_room.id)
        response = client_of_alice.patch(
            detail, {"paint_article": str(foreign_article.id)}, format="json"
        )
        assert response.status_code == 400

    def test_a_reader_changes_nothing(
        self, api_client: APIClient, reader: User, alice_home: Home, owner_room: Room, tin: Article
    ) -> None:
        api_client.force_authenticate(reader)
        detail = api("room-detail", alice_home, room_id=owner_room.id)
        assert (
            api_client.patch(detail, {"paint_article": str(tin.id)}, format="json").status_code
            == 403
        )

    def test_articles_carry_their_rooms_and_can_be_listed_by_room(
        self, client_of_alice: APIClient, alice_home: Home, owner_room: Room, hall: Room
    ) -> None:
        created = client_of_alice.post(
            api("article-list", alice_home),
            {"name": "Tape", "rooms": [str(owner_room.id)]},
            format="json",
        )
        assert created.status_code == 201, created.content
        assert created.json()["rooms"] == [str(owner_room.id)]
        client_of_alice.post(api("article-list", alice_home), {"name": "Lamp"}, format="json")
        listed = client_of_alice.get(api("article-list", alice_home), {"room": owner_room.id})
        assert [a["name"] for a in listed.json()["results"]] == ["Tape"]
        assert (
            client_of_alice.get(api("article-list", alice_home), {"room": hall.id}).json()[
                "results"
            ]
            == []
        )

    def test_a_room_of_another_home_is_a_400(
        self, client_of_alice: APIClient, alice_home: Home, bob: User, bob_home: Home
    ) -> None:
        elsewhere = room_services.create_room(bob, bob_home, name="Elsewhere")
        response = client_of_alice.post(
            api("article-list", alice_home),
            {"name": "Tape", "rooms": [str(elsewhere.id)]},
            format="json",
        )
        assert response.status_code == 400
        assert not Article.objects.filter(name="Tape").exists()

    def test_the_screen_and_the_api_agree_on_the_articles_of_a_room(
        self,
        signed_in: Client,
        client_of_alice: APIClient,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        tin: Article,
    ) -> None:
        services.create_article(alice, alice_home, name="By item", compatible_items=[owner_item])
        room_services.update_room(alice, owner_room, paint_article=tin)
        page = signed_in.get(room_url("detail", alice_home, owner_room)).text
        listed = client_of_alice.get(api("article-list", alice_home), {"room": owner_room.id})
        shown = [a["name"] for a in listed.json()["results"]]
        assert sorted(shown) == ["By item", "Sage paint"]
        assert all(name in page for name in shown)


class TestExportAndErasure:
    def test_the_export_holds_the_links(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        tin: Article,
    ) -> None:
        import io
        import json
        import zipfile

        services.update_article(alice, tin, rooms=[owner_room])
        room_services.update_room(alice, owner_room, paint_article=tin)
        client.force_login(alice)
        response = client.post(reverse("homes:export", kwargs={"home_id": alice_home.id}))
        data = json.loads(
            zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))).read("export.json")
        )
        assert data["stock_items"][0]["rooms"] == [str(owner_room.id)]
        assert data["rooms"][0]["memory"]["paint_article"] == str(tin.id)
        assert "paint_stock" not in data["rooms"][0]["memory"]
