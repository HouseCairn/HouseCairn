"""The heating season is no longer offered: it is custom months (docs/adr/0045, 2026-11-11).

What held it before keeps its months: tasks and projects of the database (migration, both
ways), an archive or a CSV file of before, an API client that still sends `heating`.
"""

import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.homes import csv_export, csv_import, exports, restore
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.projects import services as project_services
from housecairn.projects.models import Project
from housecairn.tasks import services as task_services
from housecairn.tasks import task_templates
from housecairn.tasks.models import Season, Task
from tests.data_support import archive_bytes

pytest_plugins = ("tests.tasks_fixtures", "tests.rooms_fixtures")

TASKS = (("tasks", "0009_materialdraw"), ("projects", "0002_links"))
LATEST = (("tasks", "0010_season_without_heating"), ("projects", "0003_season_without_heating"))


def apps_at(*targets: tuple[str, str]) -> Any:
    for app, name in targets:
        call_command("migrate", app, name, verbosity=0)
    return MigrationExecutor(connection).loader.project_state(list(targets)).apps


@pytest.mark.django_db(transaction=True)
def test_the_migration_turns_heating_into_its_months_and_back_without_loss() -> None:
    try:
        apps = apps_at(*TASKS)
        homes = apps.get_model("homes", "Home").objects
        north, south = homes.create(name="North"), homes.create(name="South", hemisphere="south")
        tasks = apps.get_model("tasks", "Task").objects
        projects = apps.get_model("projects", "Project").objects
        made = {
            "north heating": tasks.create(
                home=north, title="a", season="heating", season_start_month=10, season_end_month=4
            ),
            "south heating": tasks.create(
                home=south, title="b", season="heating", season_start_month=4, season_end_month=10
            ),
            "heating, months lost": tasks.create(home=south, title="c", season="heating"),
            "summer": tasks.create(
                home=north, title="d", season="summer", season_start_month=6, season_end_month=8
            ),
            "custom": tasks.create(
                home=north, title="e", season="custom", season_start_month=11, season_end_month=3
            ),
            "all year": tasks.create(home=north, title="f"),
        }
        north_project = projects.create(home=north, title="Insulate", season="heating")
        south_project = projects.create(home=south, title="Lag the pipes", season="heating")
        spring_project = projects.create(home=north, title="Paint", season="spring")

        apps = apps_at(*LATEST)
        tasks = apps.get_model("tasks", "Task").objects
        projects = apps.get_model("projects", "Project").objects

        def seasons() -> dict[str, tuple[str, int | None, int | None]]:
            return {
                name: tuple(
                    tasks.filter(pk=task.pk).values_list(
                        "season", "season_start_month", "season_end_month"
                    )[0]
                )
                for name, task in made.items()
            }

        after = {
            "north heating": ("custom", 10, 4),
            "south heating": ("custom", 4, 10),
            "heating, months lost": ("custom", 4, 10),
            "summer": ("summer", 6, 8),
            "custom": ("custom", 11, 3),
            "all year": ("", None, None),
        }
        assert seasons() == after
        assert not tasks.filter(season="heating").exists()

        def project(pk: Any) -> tuple[str, int | None, int | None]:
            row = projects.filter(pk=pk).values_list(
                "season", "season_start_month", "season_end_month"
            )[0]
            return tuple(row)  # type: ignore[return-value]

        assert project(north_project.pk) == ("custom", 10, 4)
        assert project(south_project.pk) == ("custom", 4, 10)
        assert project(spring_project.pk) == ("spring", None, None)

        # Back: the same months, valid before; nothing is turned into the heating season.
        apps = apps_at(*TASKS)
        tasks = apps.get_model("tasks", "Task").objects
        projects = apps.get_model("projects", "Project").objects
        assert seasons() == after
        assert project(north_project.pk) == ("custom", 10, 4)
        # And forward again: the same.
        apps = apps_at(*LATEST)
        tasks = apps.get_model("tasks", "Task").objects
        assert seasons() == after
    finally:
        call_command("migrate", verbosity=0)


pytestmark_db = pytest.mark.django_db


@pytestmark_db
class TestServicesAndApi:
    def test_a_client_of_before_still_sends_heating(self, alice: User, alice_home: Home) -> None:
        task = task_services.create_task(alice, alice_home, title="Bleed", season="heating")
        assert (task.season, task.season_start_month, task.season_end_month) == ("custom", 10, 4)
        home_services.update_home(alice, alice_home, hemisphere="south")
        task = task_services.create_task(alice, alice_home, title="Bleed", season="heating")
        assert (task.season, task.season_start_month, task.season_end_month) == ("custom", 4, 10)
        project = project_services.create_project(alice, alice_home, title="x", season="heating")
        assert (project.season, project.season_months) == ("custom", (4, 10))

    def test_the_api_takes_heating_and_answers_custom(self, alice: User, alice_home: Home) -> None:
        api = APIClient()
        api.force_authenticate(alice)
        base = f"/api/v1/homes/{alice_home.id}"
        task = api.post(f"{base}/tasks/", {"title": "Bleed", "season": "heating"}, format="json")
        assert task.status_code == 201, task.content
        assert task.json()["season"] == "custom"
        assert [task.json()["season_start_month"], task.json()["season_end_month"]] == [10, 4]
        project = api.post(
            f"{base}/projects/", {"title": "Insulate", "season": "heating"}, format="json"
        )
        assert project.status_code == 201, project.content
        assert project.json()["season"] == "custom"
        assert project.json()["season_months"] == [10, 4]

    def test_no_choice_offers_it_any_more(self) -> None:
        assert "heating" not in Season.values
        assert "Heating season" not in [str(label) for label in Season.labels]

    def test_no_task_template_uses_it(self) -> None:
        assert {t.season for t in task_templates.library().templates} <= {"", *Season.values}


def _rewrite(archive: bytes, change: Callable[[str, dict[str, Any]], None]) -> bytes:
    """The archive with its data documents changed, and its manifest digests made again."""
    source = zipfile.ZipFile(io.BytesIO(archive))
    manifest = json.loads(source.read(exports.MANIFEST))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            if info.filename.startswith("data/"):
                document = json.loads(data)
                change(info.filename, document)
                data = json.dumps(document).encode()
                manifest["entries"][info.filename] = {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
            if info.filename != exports.MANIFEST:
                target.writestr(info.filename, data)
        target.writestr(exports.MANIFEST, json.dumps(manifest))
    return out.getvalue()


@pytestmark_db
def test_an_archive_of_before_with_heating_is_restored_in_its_months(
    media_root: Path, alice: User, alice_home: Home
) -> None:
    task_services.create_task(
        alice, alice_home, title="Bleed", season="custom", season_start_month=10, season_end_month=4
    )
    task_services.create_task(alice, alice_home, title="Lost months", season="spring")
    project_services.create_project(alice, alice_home, title="Insulate")

    def as_before(name: str, document: dict[str, Any]) -> None:
        sections = document["sections"]
        for row in sections.get("tasks", []):
            row["season"] = "heating"
            if row["title"] == "Lost months":
                row["season_start_month"] = row["season_end_month"] = None
        for row in sections.get("projects", []):
            row["season"] = "heating"

    archive = _rewrite(archive_bytes(alice_home), as_before)
    home_services.erase_home(alice_home)
    result = restore.restore_bytes(alice, archive, match_people=True)
    tasks = {t.title: t for t in Task.objects.filter(home=result.home)}
    assert (tasks["Bleed"].season, tasks["Bleed"].season_start_month) == ("custom", 10)
    assert tasks["Bleed"].season_end_month == 4
    assert (tasks["Lost months"].season_start_month, tasks["Lost months"].season_end_month) == (
        10,
        4,
    )
    project = Project.objects.get(home=result.home)
    assert (project.season, project.season_months) == ("custom", (10, 4))


@pytestmark_db
@pytest.mark.parametrize("cell", ["heating", "Heating season", "Saison de chauffe"])
@pytest.mark.parametrize(("months", "stored"), [(("10", "4"), (10, 4)), (("", ""), (4, 10))])
def test_a_csv_file_of_before_with_heating_is_imported_in_its_months(
    alice: User, alice_home: Home, cell: str, months: tuple[str, str], stored: tuple[int, int]
) -> None:
    home_services.update_home(alice, alice_home, hemisphere="south")
    task_services.create_task(alice, alice_home, title="Template row")
    data, _name = csv_export.build_csv(alice_home, csv_export.ENTITIES["tasks"])
    lines = data.decode("utf-8").removeprefix(csv_export.BOM).splitlines()
    header = lines[0].split(",")
    row = dict.fromkeys(header, "")
    row.update(
        title="Bleed",
        priority="normal",
        repeat_mode="once",
        repeat_unit="month",
        repeat_interval="1",
        hide_days_before="0",
        season=cell,
        season_start_month=months[0],
        season_end_month=months[1],
    )
    text = ",".join(header) + "\n" + ",".join(row[h] for h in header) + "\n"
    report = csv_import.run(alice, alice_home, {"tasks": text}, confirm=True)
    assert report.refused == 0, report.as_data()
    task = Task.objects.get(home=alice_home, title="Bleed")
    assert (task.season, (task.season_start_month, task.season_end_month)) == ("custom", stored)


@pytestmark_db
def test_the_task_page_of_an_upgraded_task_says_its_months(
    alice: User, alice_home: Home, signed_in: Any
) -> None:
    task = task_services.create_task(
        alice, alice_home, title="Bleed", season="heating", repeat_mode="after_last"
    )
    page = signed_in.get(
        reverse("tasks:detail", kwargs={"home_id": alice_home.id, "task_id": task.id})
    ).text
    assert "from October to April" in page
    assert "Heating season" not in page
