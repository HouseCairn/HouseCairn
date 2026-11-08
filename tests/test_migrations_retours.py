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
