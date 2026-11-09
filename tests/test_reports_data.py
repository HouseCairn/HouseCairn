"""Export and erasure of reports with their home, migrations (docs/adr/0047)."""

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
from housecairn.homes import files
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.labels import services as label_services
from housecairn.labels.models import Label
from housecairn.reports import services as report_services
from housecairn.reports.models import Report
from housecairn.rooms.models import Item
from housecairn.stock.models import Article
from tests.rooms_support import image_bytes, upload

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
        data = json.loads(export(client, alice, alice_home).read("export.json"))
        rows = {row["id"]: row for row in data["labels"]}
        assert rows[str(active.id)]["code"] == active.code
        assert rows[str(active.id)]["target"] == str(owner_item.id)
        assert rows[str(active.id)]["kind"] == "item"
        assert rows[str(gone.id)]["code"] is None
        assert rows[str(gone.id)]["revoked_at"] is not None
        assert gone.code not in json.dumps(data)

    def test_reports_are_exported_with_their_photo_and_link(
        self,
        client: Client,
        alice: User,
        reader: User,
        alice_home: Home,
        owner_item: Item,
        media_root: Path,
    ) -> None:
        report = report_services.create_report(
            reader, alice_home, title="Crack", item=owner_item, photo=upload(image_bytes())
        )
        plain = report_services.create_report(reader, alice_home, title="Drip")
        task = report_services.make_task(alice, plain)
        report_services.close_report(alice, report, resolution="no_action")
        archive = export(client, alice, alice_home)
        data = json.loads(archive.read("export.json"))
        rows = {row["id"]: row for row in data["reports"]}
        assert rows[str(report.id)]["title"] == "Crack"
        assert rows[str(report.id)]["status"] == "no_action"
        assert rows[str(report.id)]["item"] == str(owner_item.id)
        assert rows[str(report.id)]["reporter"] == "reader@example.com"
        assert rows[str(report.id)]["closed_at"] is not None
        assert rows[str(plain.id)]["task"] == str(task.id)
        assert rows[str(plain.id)]["file"] is None
        name = rows[str(report.id)]["file"]
        assert name == f"files/reports/{report.id}.jpg"
        assert archive.read(name) == Path(report.photo.path).read_bytes()
        assert name in {f["path"] for f in data["files"]}

    def test_nothing_of_another_home_is_in_the_archive(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        bob: User,
        bob_home: Home,
        owner_item: Item,
        foreign_item: Item,
        media_root: Path,
    ) -> None:
        label_services.create_label(alice, alice_home, kind="item", target_id=owner_item.id)
        theirs = label_services.create_label(bob, bob_home, kind="item", target_id=foreign_item.id)[
            0
        ]
        secret = report_services.create_report(
            bob, bob_home, title="Bob's secret", photo=upload(image_bytes())
        )
        archive = export(client, alice, alice_home)
        raw = archive.read("export.json").decode()
        for foreign in (theirs.code, str(theirs.id), "Bob's secret", str(secret.id)):
            assert foreign not in raw
        assert not [n for n in archive.namelist() if str(secret.id) in n]

    def test_a_missing_photo_is_listed_without_one(
        self, client: Client, alice: User, alice_home: Home, media_root: Path
    ) -> None:
        report = report_services.create_report(
            alice, alice_home, title="Gone", photo=upload(image_bytes())
        )
        Path(report.photo.path).unlink()
        data = json.loads(export(client, alice, alice_home).read("export.json"))
        assert [(r["title"], r["file"]) for r in data["reports"]] == [("Gone", None)]

    def test_a_stored_name_that_leaves_the_home_folder_is_never_read(
        self, alice: User, alice_home: Home, bob: User, bob_home: Home, media_root: Path
    ) -> None:
        from housecairn.reports import exports

        theirs = report_services.create_report(
            bob, bob_home, title="t", photo=upload(image_bytes())
        )
        mine = report_services.create_report(
            alice, alice_home, title="m", photo=upload(image_bytes())
        )
        Report.objects.filter(id=mine.id).update(
            photo=f"{bob_home.id}/{Path(theirs.photo.name).name}"
        )
        mine.refresh_from_db()
        assert exports._stored_file(mine) is None
        Report.objects.filter(id=mine.id).update(photo="../../etc/passwd")
        mine.refresh_from_db()
        assert exports._stored_file(mine) is None


class TestErasure:
    def test_deleting_a_home_removes_its_labels_reports_and_photos_and_only_its(
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
        report_services.create_report(alice, alice_home, title="a", photo=upload(image_bytes()))
        kept_label = label_services.create_label(
            bob, bob_home, kind="item", target_id=foreign_item.id
        )[0]
        kept_report = report_services.create_report(
            bob, bob_home, title="b", photo=upload(image_bytes())
        )
        assert (media_root / "reports" / str(alice_home.id)).exists()
        delete_home(alice, alice_home, "Main house")
        assert list(Label.objects.all()) == [kept_label]
        assert list(Report.objects.all()) == [kept_report]
        assert not (media_root / "reports" / str(alice_home.id)).exists()
        assert Path(kept_report.photo.path).is_file()

    def test_a_task_made_from_a_report_can_go_without_taking_the_report(
        self, alice: User, alice_home: Home
    ) -> None:
        from housecairn.tasks import services as task_services

        report = report_services.create_report(alice, alice_home, title="x")
        task = report_services.make_task(alice, report)
        task_services.delete_task(alice, task)
        report.refresh_from_db()
        assert report.deleted_at is None
        assert report.task_id == task.id  # the link stays; the screens hide a deleted task

    def test_the_account_of_a_reporter_can_go_and_the_report_stays(
        self, alice: User, alice_home: Home, reader: User
    ) -> None:
        report = report_services.create_report(reader, alice_home, title="x")
        User.objects.filter(pk=reader.pk).delete()
        report.refresh_from_db()
        assert report.reporter is None
        assert report_services.reporter_name(report.reporter) == "a former member"

    def test_the_folder_is_declared(self) -> None:
        assert "reports" in files.MEDIA_FOLDERS


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("app", "table"), [("labels", "labels_label"), ("reports", "reports_report")]
)
def test_the_migration_is_reversible(app: str, table: str) -> None:
    call_command("migrate", app, "zero", verbosity=0)
    assert table not in connection.introspection.table_names()
    call_command("migrate", app, verbosity=0)
    assert table in connection.introspection.table_names()
