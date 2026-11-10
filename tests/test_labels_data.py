"""Export and erasure of labels with their home, migration (docs/adr/0047)."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.labels import services as label_services
from housecairn.labels.models import Label
from housecairn.rooms.models import Item
from housecairn.stock.models import Article
from tests.data_support import export_data

pytest_plugins = ("tests.rooms_fixtures", "tests.stock_fixtures")
pytestmark = pytest.mark.django_db


def export(client: Client, actor: User, home: Home) -> zipfile.ZipFile:
    client.force_login(actor)
    response = client.post(reverse("homes:export", kwargs={"home_id": home.id}))
    assert response.status_code == 200
    return zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))


def delete_home(actor: User, home: Home, name: str) -> None:
    with TestCase.captureOnCommitCallbacks(execute=True):
        home_services.delete_home(actor, home, confirmation=name)


class TestExport:
    def test_labels_are_exported_with_their_code_unless_revoked(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        owner_item: Item,
        article: Article,
    ) -> None:
        active = label_services.create_label(
            alice, alice_home, kind="item", target_id=owner_item.id
        )[0]
        gone = label_services.create_label(alice, alice_home, kind="article", target_id=article.id)[
            0
        ]
        label_services.revoke_label(alice, gone)
        data = export_data(export(client, alice, alice_home))
        rows = {row["id"]: row for row in data["labels"]}
        assert rows[str(active.id)]["code"] == active.code
        assert rows[str(active.id)]["item"] == str(owner_item.id)
        assert rows[str(active.id)]["kind"] == "item"
        assert rows[str(gone.id)]["code"] is None
        assert rows[str(gone.id)]["revoked_at"] is not None
        assert gone.code not in json.dumps(data)


class TestErasure:
    def test_deleting_a_home_removes_its_labels_and_only_its(
        self,
        alice: User,
        alice_home: Home,
        bob: User,
        bob_home: Home,
        owner_item: Item,
        foreign_item: Item,
        media_root: Path,
    ) -> None:
        label_services.create_label(alice, alice_home, kind="item", target_id=owner_item.id)
        revoked = label_services.create_label(
            alice, alice_home, kind="room", target_id=owner_item.room_id
        )[0]
        label_services.revoke_label(alice, revoked)
        kept_label = label_services.create_label(
            bob, bob_home, kind="item", target_id=foreign_item.id
        )[0]
        delete_home(alice, alice_home, "Main house")
        assert list(Label.objects.all()) == [kept_label]


@pytest.mark.django_db(transaction=True)
def test_the_migration_is_reversible() -> None:
    app, table = "labels", "labels_label"
    call_command("migrate", app, "zero", verbosity=0)
    assert table not in connection.introspection.table_names()
    call_command("migrate", app, verbosity=0)
    assert table in connection.introspection.table_names()
