"""Export of projects, erasure of their files with the home, reversible migration (adr 0050)."""

import datetime
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
from housecairn.projects import services
from housecairn.projects.models import BudgetLine, Project, Quote
from housecairn.tasks import services as task_services
from tests.rooms_support import image_bytes, upload
from tests.tasks_fixtures import PDF

pytest_plugins = ("tests.rooms_fixtures", "tests.projects_fixtures")
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
    def test_everything_of_the_projects_is_in_the_archive_and_nothing_of_another_home(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
        quote: Quote,
        foreign_project: Project,
        media_root: Path,
    ) -> None:
        services.accept_quote(alice, quote, labour_line)
        services.update_line(alice, labour_line, paid=Decimal("120.00"))
        services.update_quote(alice, quote, paperless_id=42, issued_on=datetime.date(2026, 6, 1))
        task = services.add_task(alice, living_room_project, title="Mask the floor")
        photo = services.add_file(
            alice, living_room_project, upload=upload(image_bytes(gps=True), "wall.jpg")
        )
        document = services.add_file(
            alice, living_room_project, upload=upload(PDF, "quote.pdf"), quote=quote
        )
        services.set_envelope(alice, alice_home, year=2026, amount=Decimal("5000"))

        archive = export(client, alice, alice_home)
        raw = archive.read("export.json").decode()
        data = json.loads(raw)
        (project,) = data["projects"]
        assert (project["title"], project["status"]) == ("Paint the living room", "idea")
        lines = {line["label"]: line for line in data["project_budget_lines"]}
        assert lines["Painter"]["planned"] == "500.00"
        assert lines["Painter"]["committed"] == "620.00"
        assert lines["Painter"]["paid"] == "120.00"
        assert lines["Paint"]["committed"] == "0"
        (exported,) = data["project_quotes"]
        assert (exported["amount"], exported["status"], exported["budget_line"]) == (
            "620.00",
            "accepted",
            str(labour_line.id),
        )
        assert (exported["paperless_id"], exported["issued_on"]) == (42, "2026-06-01")
        assert exported["contractor"] == str(quote.contractor_id)
        (link,) = data["project_tasks"]
        assert (link["project"], link["task"]) == (str(living_room_project.id), str(task.id))
        assert data["project_envelopes"] == [
            {"id": data["project_envelopes"][0]["id"], "year": 2026, "amount": "5000.00"}
        ]
        files = {f["id"]: f for f in data["project_files"]}
        assert files[str(photo.id)]["file"] == f"files/projects/{photo.id}.jpg"
        assert files[str(document.id)]["file"] == f"files/projects/{document.id}.pdf"
        assert files[str(document.id)]["quote"] == str(quote.id)
        assert archive.read(f"files/projects/{photo.id}.jpg") == Path(photo.file.path).read_bytes()
        assert b"Exif" not in archive.read(f"files/projects/{photo.id}.jpg")
        assert archive.read(f"files/projects/{document.id}.pdf") == PDF
        for foreign in (
            "Foreign project",
            str(foreign_project.id),
            str(foreign_project.lines.get().id),
        ):
            assert foreign not in raw
        assert not [n for n in archive.namelist() if str(foreign_project.id) in n]
        # Money is text, never a number a reader could round.
        assert all(isinstance(line["planned"], str) for line in data["project_budget_lines"])

    def test_a_missing_file_is_listed_without_a_path_and_deleted_things_are_left_out(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        quote: Quote,
        labour_line: BudgetLine,
    ) -> None:
        gone = services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        Path(gone.file.path).unlink()
        services.delete_quote(alice, quote)
        services.delete_line(alice, labour_line)
        dead = services.create_project(alice, alice_home, title="Dead", budget=Decimal("5"))
        services.add_task(alice, dead, title="Dead task")
        services.delete_project(alice, dead)
        data = json.loads(export(client, alice, alice_home).read("export.json"))
        assert [p["title"] for p in data["projects"]] == ["Paint the living room"]
        assert [line["label"] for line in data["project_budget_lines"]] == ["Paint"]
        assert data["project_quotes"] == []
        assert data["project_tasks"] == []
        assert [(f["id"], f["file"]) for f in data["project_files"]] == [(str(gone.id), None)]

    def test_a_stored_name_that_leaves_the_home_folder_is_never_read(
        self,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        living_room_project: Project,
        foreign_project: Project,
        media_root: Path,
    ) -> None:
        from housecairn.projects import exports
        from housecairn.projects.models import ProjectFile

        theirs = services.add_file(bob, foreign_project, upload=upload(image_bytes()))
        mine = services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        ProjectFile.objects.filter(id=mine.id).update(
            file=f"{bob_home.id}/{Path(theirs.file.name).name}"
        )
        mine.refresh_from_db()
        assert exports._stored_file(mine) is None
        ProjectFile.objects.filter(id=mine.id).update(file="../../etc/passwd")
        mine.refresh_from_db()
        assert exports._stored_file(mine) is None
        assert list(exports._files(alice_home)) == []


class TestErasure:
    def test_deleting_the_home_erases_its_project_files_and_only_its_own(
        self,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        living_room_project: Project,
        foreign_project: Project,
        quote: Quote,
        media_root: Path,
    ) -> None:
        mine = services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        document = services.add_file(
            alice, living_room_project, upload=upload(PDF, "q.pdf"), quote=quote
        )
        theirs = services.add_file(bob, foreign_project, upload=upload(image_bytes()))
        folder = media_root / "projects" / str(alice_home.id)
        assert Path(mine.file.path).parent == folder
        assert Path(document.file.path).is_file()
        delete_home(alice, alice_home, "Main house")
        assert not folder.exists()
        assert Path(theirs.file.path).is_file()
        assert not Project.objects.filter(home_id=alice_home.id).exists()
        assert not Project.all_objects.filter(home_id=alice_home.id).exists()
        assert Project.objects.filter(id=foreign_project.id).exists()

    def test_the_rows_go_with_the_home_even_when_soft_deleted(
        self, alice: User, alice_home: Home, living_room_project: Project, quote: Quote
    ) -> None:
        task = services.add_task(alice, living_room_project, title="T")
        services.delete_quote(alice, quote)
        services.delete_project(alice, living_room_project)
        services.set_envelope(alice, alice_home, year=2026, amount=Decimal("1"))
        delete_home(alice, alice_home, "Main house")
        from housecairn.projects.models import AnnualEnvelope, ProjectTask

        for model in (Project, BudgetLine, Quote, ProjectTask, AnnualEnvelope):
            assert not model.all_objects.count(), model
        assert not task_services.tasks_of(alice_home).filter(id=task.id).exists()

    def test_a_home_with_an_accepted_quote_can_be_erased(
        self,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
        quote: Quote,
    ) -> None:
        services.accept_quote(alice, quote, labour_line)
        delete_home(alice, alice_home, "Main house")
        assert not Quote.all_objects.filter(home_id=alice_home.id).exists()
        assert not BudgetLine.all_objects.filter(home_id=alice_home.id).exists()
        assert not Project.all_objects.filter(home_id=alice_home.id).exists()

    def test_an_account_with_an_accepted_quote_can_be_erased(
        self,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
        quote: Quote,
    ) -> None:
        from housecairn.accounts import services as account_services

        services.accept_quote(alice, quote, labour_line)
        account_services.delete_account(alice)
        assert not User.objects.filter(pk=alice.pk).exists()
        assert not Home.objects.filter(pk=alice_home.pk).exists()
        assert not Quote.all_objects.filter(home_id=alice_home.id).exists()

    def test_erasing_a_line_for_good_takes_its_accepted_quotes_along(
        self,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
        quote: Quote,
    ) -> None:
        services.accept_quote(alice, quote, labour_line)
        BudgetLine.all_objects.filter(id=labour_line.id).delete()
        assert not Quote.all_objects.filter(id=quote.id).exists()

    def test_the_database_keeps_a_task_in_one_project(
        self, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        from django.db import IntegrityError, transaction

        from housecairn.projects.models import ProjectTask

        other = services.create_project(alice, alice_home, title="Other")
        task = services.add_task(alice, living_room_project, title="T")
        # Not through the service, which would refuse it first.
        with pytest.raises(IntegrityError), transaction.atomic():
            ProjectTask.objects.create(home=alice_home, project=other, task=task)
        with pytest.raises(IntegrityError), transaction.atomic():
            ProjectTask.objects.create(home=alice_home, project=living_room_project, task=task)
        assert ProjectTask.all_objects.filter(task=task).count() == 1

    def test_the_folder_is_declared(self) -> None:
        from housecairn.homes import files

        assert "projects" in files.MEDIA_FOLDERS

    def test_the_export_registers_every_section(self) -> None:
        from housecairn.homes import exports

        for name in (
            "projects",
            "project_budget_lines",
            "project_quotes",
            "project_files",
            "project_tasks",
            "project_envelopes",
        ):
            assert name in exports.EXPORTERS


@pytest.mark.django_db(transaction=True)
def test_the_projects_migration_is_reversible() -> None:
    executor = MigrationExecutor(connection)
    assert executor.loader.graph.leaf_nodes("projects")
    call_command("migrate", "projects", "zero", verbosity=0)
    assert "projects_project" not in connection.introspection.table_names()
    # The tasks, the rooms and the homes are untouched by the way back.
    assert "tasks_task" in connection.introspection.table_names()
    call_command("migrate", "projects", verbosity=0)
    assert "projects_project" in connection.introspection.table_names()
