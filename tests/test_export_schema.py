"""The published JSON Schema of the archive agrees with the registry and with real archives."""

import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from django.core.management import call_command

from housecairn.accounts.models import User
from housecairn.homes.management.commands.export_schema import PUBLISHED, render
from housecairn.homes.models import Home, Role
from tests.data_support import archive_bytes, fill_home

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]


def test_the_published_schema_is_the_one_of_the_registry() -> None:
    assert (ROOT / PUBLISHED).read_text(encoding="utf-8") == render(), "run manage.py export_schema"
    call_command("export_schema", "--check", "--file", str(ROOT / PUBLISHED))


def test_a_full_archive_validates_against_the_schema(
    media_root: Path,
    alice: User,
    alice_home: Home,
    make_user: Callable[..., User],
    add_member: Callable[..., Any],
) -> None:
    member = make_user("member@example.com")
    add_member(alice_home, member, Role.MEMBER)
    fill_home(alice, member, alice_home)
    published = json.loads((ROOT / PUBLISHED).read_text(encoding="utf-8"))
    archive = zipfile.ZipFile(io.BytesIO(archive_bytes(alice_home)))
    manifest = json.loads(archive.read("manifest.json"))
    jsonschema.validate(manifest, {**published["$defs"]["manifest"], "$defs": published["$defs"]})
    for app in manifest["apps"]:
        document = json.loads(archive.read(f"data/{app}.json"))
        jsonschema.validate(document, published["$defs"]["documents"][app])


def test_the_schema_refuses_an_unknown_field(
    media_root: Path, alice: User, alice_home: Home
) -> None:
    published = json.loads((ROOT / PUBLISHED).read_text(encoding="utf-8"))
    document = json.loads(
        zipfile.ZipFile(io.BytesIO(archive_bytes(alice_home))).read("data/homes.json")
    )
    document["sections"]["members"][0]["password"] = "x"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, published["$defs"]["documents"]["homes"])
