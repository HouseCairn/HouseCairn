"""The forms of a room: the type comes first, the memory explains each field."""

import pytest
from django.test import Client
from django.urls import reverse

from housecairn.homes.models import Home
from housecairn.rooms.models import Room

pytest_plugins = ("tests.rooms_fixtures",)

pytestmark = pytest.mark.django_db


def create_url(home: Home) -> str:
    return reverse("rooms:create", kwargs={"home_id": home.id})


class TestRoomForm:
    def test_the_type_is_the_first_field_and_nothing_is_preselected(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        html = signed_in.get(create_url(alice_home)).content.decode()
        assert html.index('name="kind"') < html.index('name="name"')
        assert '<option value="" selected>Choose a type</option>' in html
        assert "task templates" in html
        assert 'src="/static/js/room-form.js"' in html or "js/room-form" in html

    def test_a_name_left_empty_takes_the_label_of_the_type(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        signed_in.post(create_url(alice_home), {"kind": "kitchen", "name": ""})
        assert Room.objects.get().name == "Kitchen"

    def test_a_name_given_is_kept(self, signed_in: Client, alice_home: Home) -> None:
        signed_in.post(create_url(alice_home), {"kind": "kitchen", "name": "Summer kitchen"})
        room = Room.objects.get()
        assert (room.kind, room.name) == ("kitchen", "Summer kitchen")

    def test_other_needs_a_name(self, signed_in: Client, alice_home: Home) -> None:
        page = signed_in.post(create_url(alice_home), {"kind": "other", "name": "  "})
        assert page.status_code == 200
        assert "Give the room a name." in page.content.decode()
        assert Room.objects.count() == 0

    def test_a_type_is_required(self, signed_in: Client, alice_home: Home) -> None:
        page = signed_in.post(create_url(alice_home), {"kind": "", "name": "Den"})
        assert page.status_code == 200
        assert Room.objects.count() == 0

    def test_editing_keeps_the_type_chosen(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        url = reverse("rooms:edit", kwargs={"home_id": alice_home.id, "room_id": owner_room.id})
        html = signed_in.get(url).content.decode()
        assert "Choose a type" not in html
        signed_in.post(url, {"kind": "office", "name": ""})
        owner_room.refresh_from_db()
        assert (owner_room.kind, owner_room.name) == ("office", "Office")


class TestMemoryForm:
    def test_it_says_what_the_memory_keeps_and_helps_every_field(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        url = reverse("rooms:memory", kwargs={"home_id": alice_home.id, "room_id": owner_room.id})
        html = signed_in.get(url).content.decode()
        assert "what you can no longer see once the work is finished" in html
        assert html.count("Example") >= 8
        assert "Paint left in stock" in html or "Paint left in stock".lower() in html.lower()


INVISIBLE = ["\u200b", "\x07\u202e", " \u200b\ufeff "]


class TestNameMadeOfInvisibleCharacters:
    """Cleaning a name can leave nothing: that is an empty name, not a server error."""

    @pytest.mark.parametrize("name", INVISIBLE)
    def test_create_takes_the_label_of_the_type(
        self, signed_in: Client, alice_home: Home, name: str
    ) -> None:
        response = signed_in.post(create_url(alice_home), {"kind": "kitchen", "name": name})
        assert response.status_code == 302
        assert Room.objects.get().name == "Kitchen"

    @pytest.mark.parametrize("name", INVISIBLE)
    def test_create_other_shows_the_form_again_with_the_error(
        self, signed_in: Client, alice_home: Home, name: str
    ) -> None:
        response = signed_in.post(create_url(alice_home), {"kind": "other", "name": name})
        assert response.status_code == 200
        assert "Give the room a name." in response.content.decode()
        assert Room.objects.count() == 0

    @pytest.mark.parametrize("name", INVISIBLE)
    def test_edit_to_a_type_with_a_label_takes_it(
        self, signed_in: Client, alice_home: Home, owner_room: Room, name: str
    ) -> None:
        url = reverse("rooms:edit", kwargs={"home_id": alice_home.id, "room_id": owner_room.id})
        response = signed_in.post(url, {"kind": "bedroom", "name": name})
        assert response.status_code == 302
        owner_room.refresh_from_db()
        assert owner_room.name == "Bedroom"

    @pytest.mark.parametrize("name", INVISIBLE)
    def test_edit_other_shows_the_form_again_with_the_error(
        self, signed_in: Client, alice_home: Home, owner_room: Room, name: str
    ) -> None:
        before = owner_room.name
        url = reverse("rooms:edit", kwargs={"home_id": alice_home.id, "room_id": owner_room.id})
        response = signed_in.post(url, {"kind": "other", "name": name})
        assert response.status_code == 200
        assert "Give the room a name." in response.content.decode()
        owner_room.refresh_from_db()
        assert owner_room.name == before

    def test_a_rule_of_the_service_the_form_missed_shows_as_an_error(
        self,
        signed_in: Client,
        alice_home: Home,
        owner_room: Room,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from django.core.exceptions import ValidationError

        from housecairn.rooms import services

        def refuse(*args: object, **kwargs: object) -> None:
            raise ValidationError("The service refuses it.")

        monkeypatch.setattr(services, "create_room", refuse)
        monkeypatch.setattr(services, "update_room", refuse)
        edit = reverse("rooms:edit", kwargs={"home_id": alice_home.id, "room_id": owner_room.id})
        for url in (create_url(alice_home), edit):
            response = signed_in.post(url, {"kind": "kitchen", "name": "Den"})
            assert response.status_code == 200
            assert "The service refuses it." in response.content.decode()
