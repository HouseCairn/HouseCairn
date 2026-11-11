"""The item form: brands suggested from the home, the contract as a contractor and a number."""

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.rooms import services
from housecairn.rooms.models import Item, Room
from housecairn.tasks import services as task_services

pytest_plugins = ("tests.rooms_fixtures",)

pytestmark = pytest.mark.django_db


def create_url(home: Home, room: Room) -> str:
    return reverse("rooms:item-create", kwargs={"home_id": home.id, "room_id": room.id})


class TestBrandSuggestions:
    def test_the_brands_of_the_home_are_suggested_once_each(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room
    ) -> None:
        for name, brand in [
            ("Boiler", "Acme"),
            ("Oven", "acme"),
            ("Fridge", "Zenith"),
            ("Rug", ""),
        ]:
            services.create_item(alice, owner_room, name=name, brand=brand)
        html = signed_in.get(create_url(alice_home, owner_room)).content.decode()
        assert '<datalist id="brand-suggestions">' in html
        assert html.count('<option value="Acme">') == 1
        assert '<option value="Zenith">' in html
        assert html.index('value="Acme"') < html.index('value="Zenith"')
        assert 'list="brand-suggestions"' in html

    def test_a_brand_never_entered_is_still_kept(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        signed_in.post(
            create_url(alice_home, owner_room),
            {"room": owner_room.id, "name": "Kettle", "kind": "equipment", "brand": "Brand New"},
        )
        assert Item.objects.get(name="Kettle").brand == "Brand New"

    def test_the_brands_of_another_home_are_not_suggested(
        self, signed_in: Client, bob: User, bob_home: Home, alice_home: Home, owner_room: Room
    ) -> None:
        theirs = services.create_room(bob, bob_home, name="Hall")
        services.create_item(bob, theirs, name="Lamp", brand="SecretBrand")
        assert (
            "SecretBrand" not in signed_in.get(create_url(alice_home, owner_room)).content.decode()
        )

    def test_a_suggestion_is_escaped(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room
    ) -> None:
        services.create_item(alice, owner_room, name="X", brand='"><script>alert(1)</script>')
        html = signed_in.get(create_url(alice_home, owner_room)).content.decode()
        assert "<script>alert(1)" not in html


class TestContract:
    def test_two_fields_on_the_form_and_the_sheet(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room
    ) -> None:
        acme = task_services.create_contractor(alice, alice_home, name="Acme Heating")
        signed_in.post(
            create_url(alice_home, owner_room),
            {
                "room": owner_room.id,
                "name": "Boiler",
                "kind": "equipment",
                "contract_contractor": str(acme.id),
                "contract_number": "C-2024-0187",
            },
        )
        item = Item.objects.get(name="Boiler")
        assert (item.contract_contractor, item.contract_number) == (acme, "C-2024-0187")
        page = signed_in.get(
            reverse("rooms:item-detail", kwargs={"home_id": alice_home.id, "item_id": item.id})
        ).content.decode()
        assert "Acme Heating" in page
        assert "C-2024-0187" in page
        # The provider is a link to the sheet of the contractor.
        sheet = reverse(
            "tasks:contractor-detail", kwargs={"home_id": alice_home.id, "contractor_id": acme.id}
        )
        assert f'<a href="{sheet}">Acme Heating</a>' in page

    def test_the_api_reads_and_writes_both(
        self, api_client: APIClient, alice: User, alice_home: Home, owner_room: Room
    ) -> None:
        acme = task_services.create_contractor(alice, alice_home, name="Acme Heating")
        api_client.force_authenticate(alice)
        url = reverse("api-v1:home-item-list", kwargs={"home_id": alice_home.id})
        created = api_client.post(
            url,
            {
                "room": str(owner_room.id),
                "name": "Boiler",
                "contract_contractor": str(acme.id),
                "contract_number": "C-1",
            },
            format="json",
        )
        assert created.status_code == 201, created.content
        body = created.json()
        assert (body["contract_contractor"], body["contract_number"]) == (str(acme.id), "C-1")
        assert "contract_provider" not in body
        assert "contract" not in body
