"""Complete export of a home: documented JSON plus files, in one archive (docs/adr/0023).

`export.json` is versioned (`FORMAT_VERSION`); the page docs/administration/data.md
describes each part. Each app that keeps data of a home registers an exporter
here, so that a later lot cannot ship a table the export forgets; the export of
a home reads that home only, which `tests/test_export_delete.py` checks with a
second home next to it.
"""

import json
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import IO, Any

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from housecairn.accounts.names import person_name
from housecairn.homes import services
from housecairn.homes.models import Home

FORMAT = "housecairn-export"
FORMAT_VERSION = 1


@dataclass(frozen=True)
class ExportedFile:
    """A file of the home: its path inside the archive and where it is stored."""

    name: str
    source: Path


Exporter = Callable[[Home], list[dict[str, Any]]]
FileSource = Callable[[Home], Iterator[ExportedFile]]

EXPORTERS: dict[str, Exporter] = {}
FILE_SOURCES: list[FileSource] = []


def register(name: str, exporter: Exporter) -> None:
    """Add a section of `export.json` (a list of plain objects) for the app's data."""
    EXPORTERS[name] = exporter


def register_files(source: FileSource) -> None:
    FILE_SOURCES.append(source)


def _members(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(m.id),
            "email": m.user.email,
            "name": person_name(m.user),
            "role": m.role,
            "joined_at": m.created_at.isoformat(),
        }
        for m in services.members(home)
    ]


def _invitations(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(i.id),
            "email": i.email,
            "role": i.role,
            "sent_at": i.sent_at.isoformat(),
            "expires_at": i.expires_at.isoformat(),
        }
        for i in services.pending_invitations(home)
    ]


register("members", _members)
register("pending_invitations", _invitations)


def _app_version() -> str:
    try:
        return metadata.version("housecairn")
    except metadata.PackageNotFoundError:  # pragma: no cover - run from a bare checkout
        return "dev"


def document(home: Home, files: list[ExportedFile]) -> dict[str, Any]:
    """The content of `export.json` for this home, and only this home."""
    data: dict[str, Any] = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "exported_at": timezone.now().isoformat(),
        "application_version": _app_version(),
        "home": {
            "id": str(home.id),
            "name": home.name,
            "currency": home.currency,
            "required_provider": home.required_provider,
            "created_at": home.created_at.isoformat(),
        },
    }
    for name, exporter in EXPORTERS.items():
        data[name] = exporter(home)
    data["files"] = [{"path": f"files/{f.name}", "size": f.source.stat().st_size} for f in files]
    return data


README = """HouseCairn export of one home
==============================

export.json   the data of the home, as JSON (format "{format}", version {version}).
files/        the files attached to the home, under the paths export.json lists.

The format is described in the documentation: Administration > Export and deletion.
This archive holds the home it was made for and nothing of any other home.
"""


def build_archive(home: Home) -> tuple[IO[bytes], str]:
    """The archive of a home, as a file object positioned at its start, and a file name."""
    files = [f for source in FILE_SOURCES for f in source(home)]
    data = document(home, files)
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)  # noqa: SIM115
    with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "export.json", json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)
        )
        archive.writestr("README.txt", README.format(format=FORMAT, version=FORMAT_VERSION))
        for f in files:
            if f.name.startswith(("/", "..")) or ".." in Path(f.name).parts:
                raise ValueError("An exported file may not leave the archive.")
            archive.write(f.source, f"files/{f.name}")
    spool.seek(0)
    stamp = timezone.now().strftime("%Y%m%d")
    return spool, f"housecairn-{slugify(home.name) or 'home'}-{stamp}.zip"


def media_directory(home: Home) -> Path:
    """Where the files of a home are kept (used by the lots that store files)."""
    return Path(settings.MEDIA_ROOT) / "homes" / str(home.id)  # see homes.files for the others


def export_home(actor: Any, home: Home) -> tuple[IO[bytes], str]:
    """The archive of the home for one of its owners, recorded in the audit log."""
    from django.core.exceptions import PermissionDenied

    from housecairn.audit import services as audit

    if not services.is_owner(actor, home):
        raise PermissionDenied
    archive, name = build_archive(home)
    audit.record("home.exported", actor=actor, home_id=home.id, format=f"v{FORMAT_VERSION}")
    return archive, name
