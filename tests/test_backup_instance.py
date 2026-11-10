"""Backup of the whole instance and its restore, on SQLite (docs/adr/0048).

The backup is made while the database is open, then restored elsewhere (`--database-file`,
`--media-root`, `--data-dir`): the restored database holds the same rows, the files are the
same bytes, the secret key is back with mode 600, and a changed backup restores nothing.
"""

import io
import json
import sqlite3
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from housecairn.accounts.models import User
from housecairn.homes.models import Home, Role
from tests.data_support import fill_home

pytest_plugins = ("tests.rooms_fixtures",)

# The PostgreSQL path runs `pg_dump`, whose version must match the server's: the CI runner
# has an older client than its PostgreSQL service, so that path is checked by hand
# (docs/administration/backup.md), and these tests run on SQLite.
on_sqlite = pytest.mark.skipif(
    connection.vendor != "sqlite", reason="the backup of a SQLite file; pg_dump is checked by hand"
)


@pytest.fixture
def instance(
    media_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alice: User,
    alice_home: Home,
    make_user: Callable[..., User],
    add_member: Callable[..., Any],
) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "secret_key").write_text("k" * 60 + "\n")
    (data / "secret_key").chmod(0o600)
    monkeypatch.setenv("HOUSECAIRN_DATA_DIR", str(data))
    member = make_user("member@example.com")
    add_member(alice_home, member, Role.MEMBER)
    fill_home(alice, member, alice_home)
    return data


def backup(output: Path) -> Path:
    out = io.StringIO()
    call_command("backup_instance", "--output", str(output), stdout=out, stderr=io.StringIO())
    return Path(out.getvalue().strip())


@on_sqlite
@pytest.mark.django_db(transaction=True)
def test_a_backup_restores_the_database_the_files_and_the_key(
    instance: Path, tmp_path: Path, media_root: Path, alice_home: Home
) -> None:
    archive = backup(tmp_path / "backups")
    assert archive.stat().st_mode & 0o077 == 0
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        manifest = json.loads(tar.extractfile("manifest.json").read())  # type: ignore[union-attr]
    assert {"manifest.json", "database", "secret_key"} <= names
    assert manifest["database"] == "sqlite"
    media_files = sorted(
        p.relative_to(media_root).as_posix() for p in media_root.rglob("*") if p.is_file()
    )
    assert media_files
    assert sorted(n.removeprefix("media/") for n in names if n.startswith("media/")) == media_files

    target = tmp_path / "restored"
    call_command(
        "restore_instance",
        str(archive),
        "--database-file",
        str(target / "db.sqlite3"),
        "--media-root",
        str(target / "media"),
        "--data-dir",
        str(target / "data"),
        stdout=io.StringIO(),
    )

    restored = sqlite3.connect(target / "db.sqlite3")
    try:
        homes = restored.execute("SELECT name FROM homes_home").fetchall()
        tables = {
            name
            for (name,) in restored.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        counts = {
            t: restored.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]  # noqa: S608
            for t in ("rooms_room", "tasks_task", "stock_article", "projects_project")
        }
    finally:
        restored.close()
    assert homes == [(alice_home.name,)]
    assert "django_migrations" in tables
    assert counts == {"rooms_room": 2, "tasks_task": 2, "stock_article": 1, "projects_project": 1}
    for name in media_files:
        assert (target / "media" / name).read_bytes() == (media_root / name).read_bytes()
    key = target / "data" / "secret_key"
    assert key.read_text() == (instance / "secret_key").read_text()
    assert key.stat().st_mode & 0o777 == 0o600


@on_sqlite
@pytest.mark.django_db(transaction=True)
def test_restore_keeps_what_was_there_aside_and_asks_first(instance: Path, tmp_path: Path) -> None:
    archive = backup(tmp_path / "backups")
    target = tmp_path / "restored"
    target.mkdir()
    (target / "db.sqlite3").write_bytes(b"old")
    options = [
        "--database-file",
        str(target / "db.sqlite3"),
        "--media-root",
        str(target / "media"),
        "--data-dir",
        str(target / "data"),
    ]
    with pytest.raises(CommandError, match="add --yes"):
        call_command("restore_instance", str(archive), *options, stdout=io.StringIO())
    assert (target / "db.sqlite3").read_bytes() == b"old"
    call_command("restore_instance", str(archive), *options, "--yes", stdout=io.StringIO())
    aside = list(target.glob("db.sqlite3.before-restore-*"))
    assert len(aside) == 1
    assert aside[0].read_bytes() == b"old"


def _tamper(archive: Path, out: Path, change: Callable[[str, bytes], bytes | None]) -> Path:
    with tarfile.open(archive) as source, tarfile.open(out, "w") as target:
        for member in source.getmembers():
            body = source.extractfile(member).read()  # type: ignore[union-attr]
            body = change(member.name, body)
            if body is None:
                continue
            member.size = len(body)
            target.addfile(member, io.BytesIO(body))
    return out


@on_sqlite
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda name, body: body + b"x" if name == "database" else body, "changed: database"),
        (lambda name, body: None if name == "secret_key" else body, "not those of its manifest"),
    ],
)
def test_a_changed_backup_restores_nothing(
    instance: Path, tmp_path: Path, change: Any, message: str
) -> None:
    archive = _tamper(backup(tmp_path / "backups"), tmp_path / "changed.tar", change)
    target = tmp_path / "restored"
    with pytest.raises(CommandError, match=message):
        call_command(
            "restore_instance",
            str(archive),
            "--database-file",
            str(target / "db.sqlite3"),
            "--media-root",
            str(target / "media"),
            "--data-dir",
            str(target / "data"),
            stdout=io.StringIO(),
        )
    assert not (target / "db.sqlite3").exists()


@pytest.mark.django_db(transaction=True)
def test_a_name_that_leaves_its_directory_is_refused(instance: Path, tmp_path: Path) -> None:
    evil = tmp_path / "evil.tar"
    with tarfile.open(evil, "w") as tar:
        info = tarfile.TarInfo("../outside")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
        link = tarfile.TarInfo("media/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
    with pytest.raises(CommandError, match="refused"):
        call_command(
            "restore_instance",
            str(evil),
            "--database-file",
            str(tmp_path / "x.sqlite3"),
            "--data-dir",
            str(tmp_path / "d"),
            "--media-root",
            str(tmp_path / "m"),
            stdout=io.StringIO(),
        )
    assert not (tmp_path / "outside").exists()


@pytest.mark.django_db
def test_restore_home_from_the_command_line_attaches_the_people_with_an_account(
    media_root: Path,
    tmp_path: Path,
    alice: User,
    alice_home: Home,
    make_user: Callable[..., User],
    add_member: Callable[..., Any],
) -> None:
    from housecairn.homes import services
    from housecairn.homes.models import Membership
    from tests.data_support import archive_bytes

    member = make_user("member@example.com")
    add_member(alice_home, member, Role.MEMBER)
    fill_home(alice, member, alice_home)
    path = tmp_path / "home.zip"
    path.write_bytes(archive_bytes(alice_home))
    services.erase_home(alice_home)
    out = io.StringIO()
    call_command("restore_home", str(path), "--owner", "ALICE@example.com", stdout=out)
    assert "Attached again: member" in out.getvalue()
    roles = dict(
        Membership.objects.filter(home_id=alice_home.id).values_list("user__email", "role")
    )
    assert roles == {"alice@example.com": "owner", "member@example.com": "member"}
    with pytest.raises(CommandError, match="already holds"):
        call_command(
            "restore_home", str(path), "--owner", "alice@example.com", stdout=io.StringIO()
        )
    with pytest.raises(CommandError, match="No active account"):
        call_command(
            "restore_home", str(path), "--owner", "nobody@example.com", stdout=io.StringIO()
        )


def test_a_failing_pg_dump_is_a_clear_error_and_leaves_no_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On PostgreSQL the database is copied by pg_dump; its refusal is shown, not a trace."""
    import subprocess

    from housecairn.instance.management.commands import backup_instance

    class FakeConnection:
        vendor = "postgresql"

    monkeypatch.setattr(backup_instance, "connection", FakeConnection())
    monkeypatch.setattr(backup_instance.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, "", "pg_dump: error: server version mismatch")

    monkeypatch.setattr(backup_instance.subprocess, "run", run)
    monkeypatch.setenv("HOUSECAIRN_DATA_DIR", str(tmp_path))
    with pytest.raises(
        CommandError, match="pg_dump failed: pg_dump: error: server version mismatch"
    ):
        call_command("backup_instance", "--output", str(tmp_path / "out"), stdout=io.StringIO())
    assert calls[0][1:3] == ["--format=custom", "--no-owner"]
    assert not list((tmp_path / "out").glob("*.tar"))
    assert not list((tmp_path / "out").glob("*.part"))
