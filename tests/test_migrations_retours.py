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


def test_a_duration_of_zero_becomes_unset_and_the_rest_is_kept() -> None:
    try:
        apps = apps_at(("tasks", "0006_contractor_record"))
        home = make_home(apps)
        task_model = apps.get_model("tasks", "Task")
        for title, minutes in (("None", None), ("Zero", 0), ("Ninety", 90)):
            task_model.objects.create(home=home, title=title, estimated_minutes=minutes)
        apps = apps_at(("tasks", "0007_estimate_zero_unset"))
        tasks = apps.get_model("tasks", "Task").objects
        assert dict(tasks.values_list("title", "estimated_minutes")) == {
            "None": None,
            "Zero": None,
            "Ninety": 90,
        }
        # Undone, then done again: nothing else is touched.
        apps = apps_at(("tasks", "0006_contractor_record"))
        tasks = apps.get_model("tasks", "Task").objects
        assert tasks.get(title="Ninety").estimated_minutes == 90
        assert tasks.count() == 3
        apps = apps_at(("tasks", "0007_estimate_zero_unset"))
        assert apps.get_model("tasks", "Task").objects.get(title="Zero").estimated_minutes is None
    finally:
        to_latest()


def test_the_paint_left_in_stock_text_moves_to_the_notes_and_comes_back() -> None:
    try:
        apps = apps_at(("rooms", "0003_item_contract_provider_and_number"))
        home = make_home(apps)
        room_model = apps.get_model("rooms", "Room")
        room_model.objects.create(home=home, name="Hall", paint_stock="half a tin, in the garage")
        room_model.objects.create(
            home=home, name="Lounge", paint_stock="1 tin", memory_notes="Two coats"
        )
        room_model.objects.create(home=home, name="Cellar", memory_notes="Damp wall")
        apps = apps_at(("rooms", "0004_room_paint_article"))
        notes = dict(apps.get_model("rooms", "Room").objects.values_list("name", "memory_notes"))
        assert notes == {
            "Hall": "Paint left in stock: half a tin, in the garage",
            "Lounge": "Two coats\nPaint left in stock: 1 tin",
            "Cellar": "Damp wall",
        }
        assert not apps.get_model("rooms", "Room").objects.exclude(paint_article=None).exists()
        apps = apps_at(("rooms", "0003_item_contract_provider_and_number"))
        back = {
            r.name: (r.paint_stock, r.memory_notes)
            for r in apps.get_model("rooms", "Room").objects.all()
        }
        assert back == {
            "Hall": ("half a tin, in the garage", ""),
            "Lounge": ("1 tin", "Two coats"),
            "Cellar": ("", "Damp wall"),
        }
        apps = apps_at(("rooms", "0004_room_paint_article"))
        assert apps.get_model("rooms", "Room").objects.count() == 3
    finally:
        to_latest()


def test_a_unit_becomes_one_of_the_list_or_other_and_comes_back() -> None:
    try:
        apps = apps_at(("stock", "0003_article_rooms"))
        home = make_home(apps)
        article_model = apps.get_model("stock", "Article")
        units = {
            "Filter": "pieces",
            "Paint": "  Litres ",
            "Cable": "mètre",
            "Sand": "bags",
            "Tape": "ROULEAU",
            "Screws": "boîte",
            "Salt": "kg",
            "Nothing": "",
        }
        for name, unit in units.items():
            article_model.objects.create(home=home, name=name, unit=unit)
        apps = apps_at(("stock", "0004_unit_list"))
        rows = {
            a.name: (a.unit, a.unit_other) for a in apps.get_model("stock", "Article").objects.all()
        }
        assert rows == {
            "Filter": ("piece", ""),
            "Paint": ("litre", ""),
            "Cable": ("metre", ""),
            "Sand": ("other", "bags"),
            "Tape": ("roll", ""),
            "Screws": ("box", ""),
            "Salt": ("kilogram", ""),
            "Nothing": ("", ""),
        }
        apps = apps_at(("stock", "0003_article_rooms"))
        back = {a.name: a.unit for a in apps.get_model("stock", "Article").objects.all()}
        assert back == {
            "Filter": "pieces",
            "Paint": "litres",
            "Cable": "metres",
            "Sand": "bags",
            "Tape": "rolls",
            "Screws": "boxes",
            "Salt": "kilograms",
            "Nothing": "",
        }
        apps = apps_at(("stock", "0004_unit_list"))
        assert apps.get_model("stock", "Article").objects.count() == len(units)
    finally:
        to_latest()
