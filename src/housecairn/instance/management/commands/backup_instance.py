"""A consistent backup of the whole instance, in one file (docs/adr/0048).

The database is copied while the application runs: with SQLite's online backup API (as
`sqlite3 db.sqlite3 ".backup ..."`), or with `pg_dump` in its custom format for
PostgreSQL. The files of `MEDIA_ROOT` go with it, and `manifest.json` gives the SHA-256
digest of each part, which `restore_instance` checks. The archive holds every home: keep it
as safe as the server.

The secret key of `<data>/secret_key` is left out unless `--include-secret-key` asks for
it (docs/adr/0060): the stored secrets (SMTP password, secrets of sign-in providers,
addresses of notification channels) are encrypted with a key derived from it, so an archive
that held both would give them all to whoever got a copy. Keep the key apart.
"""

import datetime
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection

FORMAT = "housecairn-instance-backup"
VERSION = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def postgres_environment() -> dict[str, str]:
    """The connection of `pg_dump` and `pg_restore`, from the settings, password included."""
    db = settings.DATABASES["default"]
    env = dict(os.environ)
    for key, name in (
        ("HOST", "PGHOST"),
        ("PORT", "PGPORT"),
        ("USER", "PGUSER"),
        ("PASSWORD", "PGPASSWORD"),
        ("NAME", "PGDATABASE"),
    ):
        if db.get(key):
            env[name] = str(db[key])
    return env


def dump_database(target: Path) -> str:
    """Write the database into `target`; returns its kind (`sqlite` or `postgresql`)."""
    vendor = connection.vendor
    if vendor == "sqlite":
        connection.ensure_connection()
        destination = sqlite3.connect(target)
        try:
            connection.connection.backup(destination)
        finally:
            destination.close()
        return "sqlite"
    if vendor == "postgresql":
        program = shutil.which("pg_dump")
        if program is None:
            raise CommandError("pg_dump is not installed in this container.")
        result = subprocess.run(  # noqa: S603 - fixed arguments, the connection from the environment
            [program, "--format=custom", "--no-owner", f"--file={target}"],
            env=postgres_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            # pg_dump says why on stderr (a server newer than the client, a refused login).
            raise CommandError(f"pg_dump failed: {result.stderr.strip()[:500]}")
        return "postgresql"
    raise CommandError(f"Backups of a {vendor} database are not supported.")  # pragma: no cover


def _app_version() -> str:
    try:
        return metadata.version("housecairn")
    except metadata.PackageNotFoundError:  # pragma: no cover
        return "dev"


class Command(BaseCommand):
    help = "Back up the database and the uploaded files, in one archive (not the secret key)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--output",
            type=Path,
            default=None,
            help="directory of the archive (default: <data>/backups)",
        )
        parser.add_argument(
            "--include-secret-key",
            action="store_true",
            help=(
                "also put <data>/secret_key in the archive; whoever has the archive can then "
                "read the stored secrets"
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from housecairn.entrypoint import SECRET_KEY_FILE, data_dir

        output: Path = options["output"] or data_dir() / "backups"
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        target = output / f"housecairn-{stamp}.tar"
        if target.exists():
            raise CommandError(f"{target} already exists; wait a second and run it again.")
        with tempfile.TemporaryDirectory(dir=output) as scratch:
            work = Path(scratch)
            kind = dump_database(work / "database")
            parts = {"database": sha256(work / "database")}
            secret = data_dir() / SECRET_KEY_FILE
            media = Path(settings.MEDIA_ROOT)
            partial = target.with_suffix(".part")
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w") as archive:
                archive.add(work / "database", arcname="database")
                if options["include_secret_key"] and secret.is_file():
                    archive.add(secret, arcname="secret_key")
                    parts["secret_key"] = sha256(secret)
                files = 0
                if media.is_dir():
                    for path in sorted(media.rglob("*")):
                        if path.is_symlink() or not path.is_file():
                            continue
                        name = "media/" + path.relative_to(media).as_posix()
                        archive.add(path, arcname=name, recursive=False)
                        parts[name] = sha256(path)
                        files += 1
                manifest = {
                    "format": FORMAT,
                    "version": VERSION,
                    "database": kind,
                    "application_version": _app_version(),
                    "made_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "parts": parts,
                }
                data = json.dumps(manifest, indent=2).encode()
                info = tarfile.TarInfo("manifest.json")
                info.size = len(data)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(data))
            partial.replace(target)
        self.stdout.write(str(target))
        self.stderr.write(
            f"database ({kind}), {files} files" + (", secret key" if "secret_key" in parts else "")
        )
        if "secret_key" not in parts:
            self.stderr.write(
                "The secret key is not in the archive: keep it apart (SECRET_KEY, or "
                f"{secret}). Without it, a restore cannot read the stored secrets."
                if not options["include_secret_key"]
                else f"No {secret}: the key comes from SECRET_KEY, keep a copy of it apart."
            )
