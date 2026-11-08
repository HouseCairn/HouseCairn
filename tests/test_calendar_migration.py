"""The calendar migration undone and redone (docs/adr/0052)."""

import pytest
from django.core.management import call_command
from django.db import connection

pytestmark = pytest.mark.django_db(transaction=True)


def test_the_migration_can_be_undone_and_redone() -> None:
    try:
        call_command("migrate", "calendar", "zero", verbosity=0)
        assert "calendar_feed" not in connection.introspection.table_names()
    finally:
        call_command("migrate", verbosity=0)
    assert "calendar_feed" in connection.introspection.table_names()
