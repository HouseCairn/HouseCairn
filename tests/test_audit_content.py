"""The audit log of a home records what its people do to its content, by title only."""

import json
from collections.abc import Callable

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.audit.models import AuditEvent
from housecairn.homes import exports
from housecairn.homes.models import Home
from housecairn.rooms import services as room_services
from housecairn.tasks import services as task_services
from tests.rooms_support import image_bytes, upload
from tests.tasks_fixtures import PDF

pytest_plugins = ("tests.tasks_fixtures", "tests.rooms_fixtures")

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]


def entries(home: Home, *skip: str) -> list[tuple[str, dict[str, object]]]:
    rows = AuditEvent.objects.filter(home_id=home.id).order_by("created_at", "id")
    return [(e.action, e.detail) for e in rows if e.action not in {"home.created", *skip}]


class TestEveryActionLeavesAnEntry:
    def test_rooms(self, alice: User, alice_home: Home) -> None:
        room = room_services.create_room(alice, alice_home, name="Kitchen")
        room_services.update_room(alice, room, name="Big kitchen", paint_colour="Blue")
        room_services.delete_room(alice, room)
        assert entries(alice_home) == [
            ("room.created", {"title": "Kitchen"}),
            ("room.updated", {"title": "Big kitchen", "fields": ["name", "paint_colour"]}),
            ("room.deleted", {"title": "Big kitchen"}),
        ]

    def test_items(self, alice: User, alice_home: Home) -> None:
        room = room_services.create_room(alice, alice_home, name="Cellar")
        item = room_services.create_item(alice, room, name="Boiler")
        room_services.update_item(alice, item, contract_number="Secret number 12345")
        room_services.delete_item(alice, item)
        assert entries(alice_home, "room.created") == [
            ("item.created", {"title": "Boiler"}),
            ("item.updated", {"title": "Boiler", "fields": ["contract_number"]}),
            ("item.deleted", {"title": "Boiler"}),
        ]

    def test_tasks(self, alice: User, alice_home: Home) -> None:
        task = task_services.create_task(alice, alice_home, title="Bleed the radiators")
        task_services.update_task(alice, task, notes="Use the red key", labour_budget=40)
        task_services.delete_task(alice, task)
        assert entries(alice_home) == [
            ("task.created", {"title": "Bleed the radiators"}),
            (
                "task.updated",
                {"title": "Bleed the radiators", "fields": ["labour_budget", "notes"]},
            ),
            ("task.deleted", {"title": "Bleed the radiators"}),
        ]

    def test_photos(self, alice: User, alice_home: Home) -> None:
        room = room_services.create_room(alice, alice_home, name="Hall")
        photo = room_services.add_photo(alice, upload=upload(image_bytes()), room=room)
        room_services.delete_photo(alice, photo)
        assert entries(alice_home, "room.created") == [
            ("photo.added", {"title": "Hall", "kind": "room"}),
            ("photo.deleted", {"title": "Hall", "kind": "room"}),
        ]

    def test_attachments(self, alice: User, alice_home: Home) -> None:
        task = task_services.create_task(alice, alice_home, title="Declare the boiler")
        attachment = task_services.add_attachment(
            alice, task, upload=upload(PDF, "invoice-of-mrs-x.pdf", "application/pdf")
        )
        task_services.delete_attachment(alice, attachment)
        assert entries(alice_home, "task.created") == [
            ("attachment.added", {"title": "Declare the boiler"}),
            ("attachment.deleted", {"title": "Declare the boiler"}),
        ]

    def test_the_web_screens_leave_entries_too(self, signed_in: Client, alice_home: Home) -> None:
        signed_in.post(
            reverse("rooms:create", kwargs={"home_id": alice_home.id}),
            {"kind": "kitchen", "name": "Kitchen"},
        )
        assert [a for a, _ in entries(alice_home)] == ["room.created"]

    def test_the_other_events_of_the_home_remain(self, alice: User, alice_home: Home) -> None:
        exports.export_home(alice, alice_home)
        assert [a for a, _ in entries(alice_home)] == ["home.exported"]


class TestNoContent:
    def test_no_value_reaches_the_log(self, alice: User, alice_home: Home) -> None:
        task = task_services.create_task(
            alice,
            alice_home,
            title="Paint",
            notes="Code of the safe 0000",
            procedure="Step one: ...",
            labour_budget=120,
        )
        task_services.update_task(alice, task, material_budget=60, notes="New secret 1111")
        text = json.dumps(
            list(AuditEvent.objects.filter(home_id=alice_home.id).values_list("detail", flat=True))
        )
        for secret in ("0000", "1111", "Step one", "120", "60"):
            assert secret not in text

    def test_a_long_title_is_cut_and_a_line_break_flattened(
        self, alice: User, alice_home: Home
    ) -> None:
        task_services.create_task(alice, alice_home, title="A\nB" + "x" * 150)
        title = str(AuditEvent.objects.get(action="task.created").detail["title"])
        assert "\n" not in title
        assert len(title) <= 120


class TestScreens:
    def test_an_owner_reads_who_what_and_when(self, signed_in: Client, alice_home: Home) -> None:
        task_services.create_task(
            User.objects.get(email="alice@example.com"), alice_home, title="Sweep the chimney"
        )
        page = signed_in.get(reverse("homes:audit", kwargs={"home_id": alice_home.id}))
        content = page.content.decode()
        assert "Task added: Sweep the chimney" in content
        assert "alice" in content  # the name, as everywhere (ADR 0045)
        assert "alice@example.com" not in content

    def test_the_empty_state_explains_what_will_be_found(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        AuditEvent.objects.filter(home_id=alice_home.id).delete()
        content = signed_in.get(
            reverse("homes:audit", kwargs={"home_id": alice_home.id})
        ).content.decode()
        assert "appears here with who did it and when" in content

    def test_a_title_is_escaped(self, signed_in: Client, alice: User, alice_home: Home) -> None:
        room_services.create_room(alice, alice_home, name="<script>alert(1)</script>")
        content = signed_in.get(
            reverse("homes:audit", kwargs={"home_id": alice_home.id})
        ).content.decode()
        assert "<script>alert(1)" not in content
        assert "&lt;script&gt;" in content


class TestIsolation:
    def test_another_home_sees_nothing(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home, client: Client
    ) -> None:
        room_services.create_room(alice, alice_home, name="Secret room")
        task_services.create_task(alice, alice_home, title="Secret task")
        client.force_login(bob)
        own = client.get(reverse("homes:audit", kwargs={"home_id": bob_home.id})).content.decode()
        assert "Secret" not in own
        assert (
            client.get(reverse("homes:audit", kwargs={"home_id": alice_home.id})).status_code == 404
        )

    def test_the_api_log_is_the_homes_own(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home, api_client: APIClient
    ) -> None:
        room_services.create_room(alice, alice_home, name="Secret room")
        api_client.force_authenticate(bob)
        url = reverse("api-v1:home-audit", kwargs={"home_id": bob_home.id})
        assert "Secret" not in json.dumps(api_client.get(url).json())
        other = reverse("api-v1:home-audit", kwargs={"home_id": alice_home.id})
        assert api_client.get(other).status_code == 404

    def test_the_administrator_never_sees_them(
        self, alice: User, alice_home: Home, make_user: Callable[..., User], client: Client
    ) -> None:
        room_services.create_room(alice, alice_home, name="Secret room")
        client.force_login(make_user("admin@example.com", is_staff=True, is_superuser=True))
        assert "Secret" not in client.get(reverse("instance:audit")).content.decode()

    def test_a_reader_cannot_read_the_log(
        self, alice_home: Home, reader: User, client: Client
    ) -> None:
        client.force_login(reader)
        url = reverse("homes:audit", kwargs={"home_id": alice_home.id})
        assert client.get(url).status_code in (403, 404)
