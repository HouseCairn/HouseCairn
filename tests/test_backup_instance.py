"""Backup of the whole instance and its restore, on SQLite (docs/adr/0048).

The backup is made while the database is open, then restored elsewhere (`--database-file`,
`--media-root`, `--data-dir`): the restored database holds the same rows, the files are the
same bytes, and a changed backup restores nothing. The secret key is left out unless asked
for (docs/adr/0060); asked for, it is back with mode 600.
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


def backup(output: Path, *options: str, stderr: io.StringIO | None = None) -> Path:
    out = io.StringIO()
    call_command(
        "backup_instance",
        "--output",
        str(output),
        *options,
        stdout=out,
        stderr=stderr or io.StringIO(),
    )
    return Path(out.getvalue().strip())


def restore(archive: Path, target: Path, *options: str) -> str:
    out = io.StringIO()
    call_command(
        "restore_instance",
        str(archive),
        "--database-file",
        str(target / "db.sqlite3"),
        "--media-root",
        str(target / "media"),
        "--data-dir",
        str(target / "data"),
        *options,
        stdout=out,
    )
    return out.getvalue()


@on_sqlite
@pytest.mark.django_db(transaction=True)
def test_a_backup_restores_the_database_the_files_and_the_key_asked_for(
    instance: Path, tmp_path: Path, media_root: Path, alice_home: Home
) -> None:
    archive = backup(tmp_path / "backups", "--include-secret-key")
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
def test_the_secret_key_is_left_out_by_default(instance: Path, tmp_path: Path) -> None:
    """Whoever gets a copy of the archive must not get the key of the stored secrets with it.
    The restore leaves the key of the data directory alone, and says what to do."""
    said = io.StringIO()
    archive = backup(tmp_path / "backups", stderr=said)
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        manifest = json.loads(tar.extractfile("manifest.json").read())  # type: ignore[union-attr]
    assert "secret_key" not in names
    assert "secret_key" not in manifest["parts"]
    assert ("k" * 60).encode() not in archive.read_bytes()
    assert "secret key is not in the archive" in said.getvalue()

    target = tmp_path / "restored"
    (target / "data").mkdir(parents=True)
    (target / "data" / "secret_key").write_text("the-key-of-this-instance\n")
    out = restore(archive, target, "--yes")
    assert "Restored: database, " in out
    assert "secret key" not in out.splitlines()[0]
    assert "holds no secret key" in out
    assert "SECRET_KEY" in out
    # The key in place is kept as it is: nothing set aside, nothing replaced.
    assert (target / "data" / "secret_key").read_text() == "the-key-of-this-instance\n"
    assert not list((target / "data").glob("secret_key.before-restore-*"))
    assert (target / "db.sqlite3").is_file()


WITH_ANOTHER_KEY = (
    "With another key, the stored secrets cannot be read: enter the SMTP password and the "
    "secrets of the sign-in providers again, and add the notification channels again; everyone "
    "signs in again. The homes, their files and the accounts are restored either way."
)


@on_sqlite
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("key_from", ["file", "environment"])
def test_the_backup_names_where_the_key_in_use_is(
    instance: Path, tmp_path: Path, key_from: str
) -> None:
    """The file is named only when it holds the key in use; with the key in SECRET_KEY and
    no file, or a file that is not used, the message names SECRET_KEY alone."""
    from django.test.utils import override_settings

    key_file = instance / "secret_key"
    if key_from == "environment":
        key_file.unlink()
    said = io.StringIO()
    with override_settings(SECRET_KEY="k" * 60):
        backup(tmp_path / "backups", stderr=said)
    where = str(key_file) if key_from == "file" else "SECRET_KEY"
    assert said.getvalue().splitlines()[1:] == [
        f"The secret key is not in the archive: keep a copy of {where} apart. "
        "Without it, a restore cannot read the stored secrets."
    ]


@on_sqlite
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("generated", [False, True])
def test_the_restore_says_whether_the_key_in_place_was_just_generated(
    instance: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generated: bool
) -> None:
    """On a new data directory without SECRET_KEY, the entrypoint generates a key before the
    command runs: the restore says that key is not the one of the backup."""
    from housecairn.entrypoint import KEY_GENERATED

    archive = backup(tmp_path / "backups")
    target = tmp_path / "restored"
    (target / "data").mkdir(parents=True)
    key_file = target / "data" / "secret_key"
    key_file.write_text("a-key-generated-just-now\n")
    if generated:
        monkeypatch.setenv(KEY_GENERATED, str(key_file))
    else:
        # A key generated for another data directory says nothing of this one.
        monkeypatch.setenv(KEY_GENERATED, str(tmp_path / "elsewhere" / "secret_key"))
    out = restore(archive, target, "--yes")
    expected = (
        f"The backup holds no secret key, and {key_file} was generated just now, for this new "
        "data directory: it is not the key of the instance the backup was made on. Before you "
        "start the instance, replace it with that key: its secret_key file in place of this "
        "one, or its value in SECRET_KEY. "
        if generated
        else "The backup holds no secret key: start the instance with the key it had when the "
        "backup was made, in SECRET_KEY (or in secret_key of the data directory). "
    ) + WITH_ANOTHER_KEY
    assert out.splitlines()[1:] == [expected]
    assert key_file.read_text() == "a-key-generated-just-now\n"


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
    made = backup(tmp_path / "backups", "--include-secret-key")
    archive = _tamper(made, tmp_path / "changed.tar", change)
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
