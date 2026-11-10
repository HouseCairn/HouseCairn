"""Export, then restore on an empty instance: every field and every file comes back (docs/adr/0048).

The criterion "Restore" of the MVP: a home holding a row of every table is exported, erased
with everything it holds, and restored from its archive; the rows are compared field by
field, the many-to-many links set by set, and the files byte for byte.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.db import models

from housecairn.accounts.models import User
from housecairn.homes import exports, restore, services
from housecairn.homes.models import Home, Membership, Role
from tests.data_support import archive_bytes, export_data, fill_home

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = pytest.mark.django_db


def _value(f: models.Field[Any, Any], row: models.Model) -> Any:
    if isinstance(f, models.FileField):
        stored = getattr(row, f.name)
        return Path(stored.path).read_bytes() if stored else None
    return getattr(row, f.attname)


def snapshot(home_id: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """Every restored table of the home: id -> field -> value (files as their bytes)."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for _app, section in exports.all_sections():
        if not section.restore:
            continue
        rows: dict[str, dict[str, Any]] = {}
        for row in section.model._default_manager.filter(home_id=home_id):
            values = {f.name: _value(f, row) for f in section.fields() if f.name != "home"}
            for relation in section.many_to_many():
                values[relation.name] = sorted(
                    getattr(row, relation.name).values_list("pk", flat=True)
                )
            for spec in section.files:
                if spec.thumbnail:
                    values[spec.thumbnail + "_present"] = bool(getattr(row, spec.thumbnail))
            if section.name == "labels" and values["revoked_at"] is not None:
                # A revoked label opens nothing: its code is not exported, a new one is drawn.
                values["code"] = "revoked"
            rows[str(row.pk)] = values
        out[section.name] = rows
    return out


@pytest.fixture
def full_home(
    media_root: Path,
    alice: User,
    alice_home: Home,
    make_user: Callable[..., User],
    add_member: Callable[..., Any],
) -> tuple[Home, User]:
    member = make_user("member@example.com")
    add_member(alice_home, member, Role.MEMBER)
    fill_home(alice, member, alice_home)
    return alice_home, member


def test_every_table_of_the_home_has_rows_in_the_archive(full_home: tuple[Home, User]) -> None:
    home, _member = full_home
    data = export_data(archive_bytes(home))
    empty = sorted(s.name for _a, s in exports.all_sections() if not data[s.name])
    assert empty == []


def test_export_then_restore_gives_back_every_field_and_file(
    full_home: tuple[Home, User], alice: User
) -> None:
    home, member = full_home
    before = snapshot(home.id)
    home_row = Home.objects.values().get(pk=home.id)
    archive = archive_bytes(home)
    services.erase_home(home)
    assert snapshot(home.id) == {name: {} for name in before}

    result = restore.restore_bytes(alice, archive, match_people=True)

    assert result.home.id == home.id
    assert snapshot(home.id) == before
    assert Home.objects.values().get(pk=home.id) == home_row
    roles = dict(Membership.objects.filter(home=result.home).values_list("user__email", "role"))
    assert roles == {alice.email: Role.OWNER, member.email: Role.MEMBER}
    assert len(result.matched) == 1
    assert result.unattributed == []


def test_on_a_new_instance_people_without_an_account_are_left_unattributed(
    full_home: tuple[Home, User], alice: User
) -> None:
    home, member = full_home
    before = snapshot(home.id)
    archive = archive_bytes(home)
    services.erase_home(home)
    member.delete()

    result = restore.restore_bytes(alice, archive, match_people=True)

    after = snapshot(home.id)
    task = next(iter(after["tasks"].values()))
    assert task["assignee"] is None
    assert result.unattributed
    # Everything else is the same.
    for name, rows in before.items():
        assert set(rows) == set(after[name]), name


def test_from_the_web_only_the_person_restoring_is_matched(
    full_home: tuple[Home, User], alice: User
) -> None:
    home, member = full_home
    archive = archive_bytes(home)
    services.erase_home(home)

    result = restore.restore_bytes(alice, archive)

    assert list(Membership.objects.filter(home=result.home).values_list("user", flat=True)) == [
        alice.pk
    ]
    task = next(iter(snapshot(home.id)["tasks"].values()))
    assert task["assignee"] is None
    assert member.memberships.count() == 0
