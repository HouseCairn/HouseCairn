"""Data migrations of the test feedback: each one undone and redone, nothing lost."""

from typing import Any

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)


def apps_at(*targets: tuple[str, str]) -> Any:
    """Migrate to the given states and return the historical models there."""
    for app, name in targets:
        call_command("migrate", app, name, verbosity=0)
    executor = MigrationExecutor(connection)
    return executor.loader.project_state(list(targets)).apps


def to_latest() -> None:
    call_command("migrate", verbosity=0)


def make_home(apps: Any) -> Any:
    return apps.get_model("homes", "Home").objects.create(name="Main house")


def test_photo_categories_are_converted_and_converted_back() -> None:
    try:
        apps = apps_at(("rooms", "0001_initial"))
        home = make_home(apps)
        room = apps.get_model("rooms", "Room").objects.create(home=home, name="Hall")
        photo_model = apps.get_model("rooms", "Photo")
        for category in ("general", "open_walls"):
            photo_model.objects.create(
                home=home,
                room=room,
                category=category,
                image=f"{category}.jpg",
                thumbnail=f"{category}-t.jpg",
                content_type="image/jpeg",
                size_bytes=1,
                width=1,
                height=1,
            )
        apps = apps_at(("rooms", "0002_photo_categories"))
        photos = apps.get_model("rooms", "Photo").objects
        assert sorted(photos.values_list("category", flat=True)) == ["behind_walls", "general"]
        # Categories that did not exist before come back as "general", not lost.
        photos.filter(category="behind_walls").update(category="after")
        photos.filter(category="general").update(category="before")
        apps = apps_at(("rooms", "0001_initial"))
        photos = apps.get_model("rooms", "Photo").objects
        assert sorted(photos.values_list("category", flat=True)) == ["general", "general"]
        assert photos.count() == 2
    finally:
        to_latest()


def test_item_contract_goes_whole_to_the_provider_and_comes_back() -> None:
    try:
        apps = apps_at(("rooms", "0002_photo_categories"))
        home = make_home(apps)
        room = apps.get_model("rooms", "Room").objects.create(home=home, name="Cellar")
        item_model = apps.get_model("rooms", "Item")
        item_model.objects.create(
            home=home, room=room, name="Boiler", contract="Acme Heating, contract C-2024-0187"
        )
        item_model.objects.create(home=home, room=room, name="Pump")
        apps = apps_at(("rooms", "0003_item_contract_provider_and_number"))
        items = apps.get_model("rooms", "Item").objects
        boiler = items.get(name="Boiler")
        assert boiler.contract_provider == "Acme Heating, contract C-2024-0187"
        assert boiler.contract_number == ""
        assert items.get(name="Pump").contract_provider == ""
        items.filter(name="Boiler").update(
            contract_provider="Acme Heating", contract_number="C-2024-0187"
        )
        apps = apps_at(("rooms", "0002_photo_categories"))
        items = apps.get_model("rooms", "Item").objects
        assert items.get(name="Boiler").contract == "Acme Heating · C-2024-0187"
        assert items.get(name="Pump").contract == ""
    finally:
        to_latest()


def test_the_language_of_a_person_can_be_undone_and_redone() -> None:
    try:
        call_command("migrate", "tasks", "0003_displaypreference", verbosity=0)
        columns = {
            c.name
            for c in connection.introspection.get_table_description(
                connection.cursor(), "tasks_displaypreference"
            )
        }
        assert "language" not in columns
        call_command("migrate", "tasks", verbosity=0)
        columns = {
            c.name
            for c in connection.introspection.get_table_description(
                connection.cursor(), "tasks_displaypreference"
            )
        }
        assert "language" in columns
    finally:
        to_latest()


def test_a_window_becomes_a_predefined_season_or_a_custom_one() -> None:
    try:
        apps = apps_at(("tasks", "0004_displaypreference_language"))
        home = make_home(apps)
        task_model = apps.get_model("tasks", "Task")
        windows = {
            "Mow": (6, 8),
            "Heat": (10, 4),
            "Prune": (2, 3),
            "Garden": (4, 10),
            "Dust": (None, None),
        }
        for title, (start, end) in windows.items():
            task_model.objects.create(
                home=home, title=title, season_start_month=start, season_end_month=end
            )
        apps = apps_at(("tasks", "0005_task_season"))
        seasons = dict(apps.get_model("tasks", "Task").objects.values_list("title", "season"))
        assert seasons == {
            "Mow": "summer",
            "Heat": "heating",
            "Prune": "custom",
            "Garden": "custom",
            "Dust": "",
        }
        apps = apps_at(("tasks", "0004_displaypreference_language"))
        months = {
            title: (start, end)
            for title, start, end in apps.get_model("tasks", "Task").objects.values_list(
                "title", "season_start_month", "season_end_month"
            )
        }
        assert months == windows
        apps = apps_at(("tasks", "0005_task_season"))
        assert apps.get_model("tasks", "Task").objects.count() == len(windows)
    finally:
        to_latest()


def test_a_trade_becomes_one_of_the_list_or_other_and_comes_back() -> None:
    try:
        apps = apps_at(("tasks", "0005_task_season"))
        home = make_home(apps)
        contractor_model = apps.get_model("tasks", "Contractor")
        trades = {
            "Pipes Ltd": "Plumber",
            "Sparks": "  électricien ",
            "Heat": "Chauffagiste",
            "Pool Co": "Pool maintenance",
            "Walls": "MAÇON",
            "Nobody": "",
        }
        for name, trade in trades.items():
            contractor_model.objects.create(home=home, name=name, trade=trade, note="n")
        apps = apps_at(("tasks", "0006_contractor_record"))
        rows = {
            c.name: (c.trade, c.trade_other, c.note)
            for c in apps.get_model("tasks", "Contractor").objects.all()
        }
        assert rows == {
            "Pipes Ltd": ("plumber", "", "n"),
            "Sparks": ("electrician", "", "n"),
            "Heat": ("heating_engineer", "", "n"),
            "Pool Co": ("other", "Pool maintenance", "n"),
            "Walls": ("mason", "", "n"),
            "Nobody": ("", "", "n"),
        }
        apps = apps_at(("tasks", "0005_task_season"))
        back = {c.name: c.trade for c in apps.get_model("tasks", "Contractor").objects.all()}
        assert back == {
            "Pipes Ltd": "Plumber",
            "Sparks": "Electrician",
            "Heat": "Heating engineer",
            "Pool Co": "Pool maintenance",
            "Walls": "Mason",
            "Nobody": "",
        }
        apps = apps_at(("tasks", "0006_contractor_record"))
        assert apps.get_model("tasks", "Contractor").objects.count() == len(trades)
    finally:
        to_latest()
