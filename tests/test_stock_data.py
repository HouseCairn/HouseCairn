"""Export of stock, erasure of its files with the home, reversible migration (docs/adr/0038)."""

import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.rooms.models import Item
from housecairn.stock import exports, services
from housecairn.stock.models import Article
from tests.rooms_support import image_bytes, upload

pytest_plugins = ("tests.rooms_fixtures", "tests.stock_fixtures")
pytestmark = pytest.mark.django_db


def delete_home(actor: User, home: Home, name: str) -> None:
    with TestCase.captureOnCommitCallbacks(execute=True):
        home_services.delete_home(actor, home, confirmation=name)


def export(client: Client, actor: User, home: Home) -> zipfile.ZipFile:
    client.force_login(actor)
    response = client.post(reverse("homes:export", kwargs={"home_id": home.id}))
    assert response.status_code == 200
    return zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))


class TestExport:
    def test_articles_suppliers_movements_and_the_label_are_in_the_archive(
        self,
        client: Client,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        owner_item: Item,
        foreign_article: Article,
        media_root: Path,
    ) -> None:
        article = services.create_article(
            alice,
            alice_home,
            name="Boiler filter",
            manufacturer_reference="BF-200",
            threshold=Decimal("2"),
            compatible_items=[owner_item],
            label=upload(image_bytes(gps=True)),
        )
        services.create_supplier(
            alice, article, name="Acme", url="https://shop.example.com/a", last_price=Decimal("9.5")
        )
        services.record_movement(alice, article, kind="entry", quantity=Decimal("3"), note="bought")
        services.record_movement(alice, article, kind="inventory", quantity=Decimal("2"))
        services.create_supplier(bob, foreign_article, name="Bob supplier")
        services.record_movement(bob, foreign_article, kind="entry", quantity=Decimal("7"))

        archive = export(client, alice, alice_home)
        raw = archive.read("export.json").decode()
        data = json.loads(raw)
        (item,) = data["stock_items"]
        assert (item["name"], item["manufacturer_reference"], item["threshold"]) == (
            "Boiler filter",
            "BF-200",
            "2.00",
        )
        assert (item["quantity"], item["compatible_items"]) == ("2.00", [str(owner_item.id)])
        assert item["label"] == f"files/stock/{article.id}.jpg"
        assert item["label"].removeprefix("files/") in {
            f["path"].removeprefix("files/") for f in data["files"]
        }
        (supplier,) = data["stock_suppliers"]
        assert (supplier["article"], supplier["last_price"]) == (str(article.id), "9.50")
        assert supplier["url"] == "https://shop.example.com/a"
        assert [(m["kind"], m["quantity"], m["delta"]) for m in data["stock_movements"]] == [
            ("entry", "3.00", "3.00"),
            ("inventory", "2.00", "-1.00"),
        ]
        assert data["stock_movements"][0]["note"] == "bought"
        stored = archive.read(f"files/stock/{article.id}.jpg")
        assert stored == Path(article.label.path).read_bytes()
        # Nothing of the other home, in any form.
        for foreign in ("Foreign filter", "Bob supplier", str(foreign_article.id)):
            assert foreign not in raw
        assert not [n for n in archive.namelist() if str(foreign_article.id) in n]

    def test_a_missing_file_is_listed_without_one_and_a_deleted_article_is_left_out(
        self, client: Client, alice: User, alice_home: Home, media_root: Path
    ) -> None:
        gone = services.create_article(alice, alice_home, name="Gone", label=upload(image_bytes()))
        Path(gone.label.path).unlink()
        deleted = services.create_article(alice, alice_home, name="Deleted")
        services.create_supplier(alice, deleted, name="Orphan")
        services.record_movement(alice, deleted, kind="entry", quantity=Decimal("1"))
        services.delete_article(alice, deleted)
        data = json.loads(export(client, alice, alice_home).read("export.json"))
        assert [(a["name"], a["label"]) for a in data["stock_items"]] == [("Gone", None)]
        assert data["stock_suppliers"] == []
        assert data["stock_movements"] == []

    def test_a_stored_name_that_leaves_the_home_folder_is_never_read(
        self, alice: User, alice_home: Home, bob: User, bob_home: Home, media_root: Path
    ) -> None:
        theirs = services.create_article(bob, bob_home, name="Theirs", label=upload(image_bytes()))
        mine = services.create_article(alice, alice_home, name="Mine", label=upload(image_bytes()))
        Article.objects.filter(id=mine.id).update(
            label=f"{bob_home.id}/{Path(theirs.label.name).name}"
        )
        mine.refresh_from_db()
        assert exports._stored_file(mine) is None
        Article.objects.filter(id=mine.id).update(label="../../etc/passwd")
        mine.refresh_from_db()
        assert exports._stored_file(mine) is None
        assert list(exports._files(alice_home)) == []


class TestEraseFilesWithTheHome:
    def test_label_files_go_with_the_home_and_not_those_of_another(
        self,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        media_root: Path,
    ) -> None:
        mine = services.create_article(alice, alice_home, name="a", label=upload(image_bytes()))
        theirs = services.create_article(bob, bob_home, name="b", label=upload(image_bytes()))
        mine_dir = media_root / "stock" / str(alice_home.id)
        assert Path(mine.label.path).parent == mine_dir
        assert Path(mine.label.path).is_file()
        delete_home(alice, alice_home, "Main house")
        assert not mine_dir.exists()
        assert Path(theirs.label.path).is_file()

    def test_a_soft_deleted_article_file_goes_too(
        self, alice: User, alice_home: Home, media_root: Path
    ) -> None:
        article = services.create_article(alice, alice_home, name="a", label=upload(image_bytes()))
        services.delete_article(alice, article)
        assert (media_root / "stock" / str(alice_home.id)).exists()
        delete_home(alice, alice_home, "Main house")
        assert not (media_root / "stock" / str(alice_home.id)).exists()

    def test_the_folder_is_declared(self) -> None:
        from housecairn.homes import files

        assert "stock" in files.MEDIA_FOLDERS


@pytest.mark.django_db(transaction=True)
def test_the_stock_migration_is_reversible() -> None:
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes("stock")
    assert latest
    call_command("migrate", "stock", "zero", verbosity=0)
    assert "stock_article" not in connection.introspection.table_names()
    # Not `migrate stock`: rolling stock back also rolled back the apps that depend on it
    # (labels, reports, tasks), and only a full `migrate` brings them back. Left as they
    # were, every later test of the worker would find their tables missing.
    call_command("migrate", verbosity=0)
    assert "stock_article" in connection.introspection.table_names()
