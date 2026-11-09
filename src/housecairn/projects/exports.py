"""Projects are part of the export of their home (docs/adr/0023, 0050).

Plain objects with identifiers, dates and amounts as text, never a float. The photos, the
pictures of links and the files of quotes go into `files/projects/`, already stripped of
their metadata at upload (docs/adr/0030) or as received for a document.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from django.core.exceptions import SuspiciousFileOperation
from django.db.models import Prefetch

from housecairn.homes import exports
from housecairn.homes.models import Home
from housecairn.projects import services
from housecairn.projects.models import ProjectFile
from housecairn.projects.storage import project_storage
from housecairn.rooms.files import EXTENSIONS
from housecairn.rooms.models import Room

DOCUMENT_EXTENSIONS = {
    "application/pdf": ".pdf",
    "text/plain; charset=utf-8": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
}


def _archive_name(stored: ProjectFile) -> str:
    extension = EXTENSIONS.get(stored.content_type) or DOCUMENT_EXTENSIONS.get(
        stored.content_type, ""
    )
    return f"projects/{stored.id}{extension}"


def _stored_file(stored: ProjectFile) -> Path | None:
    """The file on disk, if it is there and inside the folder of its own home."""
    if not stored.file:
        return None
    try:
        path = Path(project_storage.path(stored.file.name)).resolve()
    except (SuspiciousFileOperation, ValueError, OSError):
        return None
    folder = (Path(project_storage.location) / str(stored.home_id)).resolve()
    if path.parent != folder or not path.is_file():
        return None
    return path


def _money(value: Any) -> str:
    return str(value)


def _projects(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "goal": p.goal,
            "status": p.status,
            "priority": p.priority,
            "rooms": [str(r.pk) for r in p.rooms.all()],
            "estimated_minutes": p.estimated_minutes,
            "season": p.season,
            "season_start_month": p.season_start_month,
            "season_end_month": p.season_end_month,
            "created_at": p.created_at.isoformat(),
        }
        for p in services.projects_of(home)
        .order_by("created_at", "id")
        .prefetch_related(
            # One query for the rooms of all the projects, in the order of the identifiers.
            Prefetch("rooms", queryset=Room.objects.order_by("id"))
        )
    ]


def _lines(home: Home) -> list[dict[str, Any]]:
    all_lines = list(services.lines_of(home).order_by("created_at", "id"))
    committed = services.committed_by_line(all_lines)
    return [
        {
            "id": str(line.id),
            "project": str(line.project_id),
            "label": line.label,
            "nature": line.nature,
            "planned": _money(line.planned),
            "committed": _money(committed.get(line.id, 0)),
            "paid": _money(line.paid),
            "created_at": line.created_at.isoformat(),
        }
        for line in all_lines
    ]


def _quotes(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(q.id),
            "project": str(q.project_id),
            "contractor": str(q.contractor_id) if q.contractor_id else None,
            "amount": _money(q.amount),
            "issued_on": q.issued_on.isoformat() if q.issued_on else None,
            "valid_until": q.valid_until.isoformat() if q.valid_until else None,
            "status": q.status,
            "budget_line": str(q.budget_line_id) if q.budget_line_id else None,
            "note": q.note,
            "paperless_id": q.paperless_id,
            "paperless_url": q.paperless_url,
            "created_at": q.created_at.isoformat(),
        }
        for q in services.quotes_of(home).order_by("created_at", "id")
    ]


def _project_files(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(f.id),
            "project": str(f.project_id),
            "quote": str(f.quote_id) if f.quote_id else None,
            "name": f.name,
            "content_type": f.content_type,
            "is_image": f.is_image,
            "size_bytes": f.size_bytes,
            "width": f.width,
            "height": f.height,
            "created_at": f.created_at.isoformat(),
            "file": f"files/{_archive_name(f)}" if _stored_file(f) else None,
        }
        for f in services.files_of(home).order_by("created_at", "id")
    ]


def _links(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(link.id),
            "project": str(link.project_id),
            "url": link.url,
            "title": link.title,
            "image": str(link.image_id) if link.image_id else None,
            "created_at": link.created_at.isoformat(),
        }
        for link in services.inspiration_links_of(home).order_by("created_at", "id")
    ]


def _tasks(home: Home) -> list[dict[str, Any]]:
    return [
        {"id": str(link.id), "project": str(link.project_id), "task": str(link.task_id)}
        for link in services.links_of(home).order_by("created_at", "id")
    ]


def _envelopes(home: Home) -> list[dict[str, Any]]:
    return [
        {"id": str(e.id), "year": e.year, "amount": _money(e.amount)}
        for e in services.envelopes_of(home).order_by("year")
    ]


def _files(home: Home) -> Iterator[exports.ExportedFile]:
    for stored in ProjectFile.objects.filter(home=home).order_by("created_at", "id"):
        source = _stored_file(stored)
        if source is not None:
            yield exports.ExportedFile(name=_archive_name(stored), source=source)


def register() -> None:
    exports.register("projects", _projects)
    exports.register("project_budget_lines", _lines)
    exports.register("project_quotes", _quotes)
    exports.register("project_files", _project_files)
    exports.register("project_links", _links)
    exports.register("project_tasks", _tasks)
    exports.register("project_envelopes", _envelopes)
    exports.register_files(_files)
