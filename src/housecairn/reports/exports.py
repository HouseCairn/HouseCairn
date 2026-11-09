"""Reports are part of the export of their home (docs/adr/0023, 0047).

Plain objects with identifiers and dates as text. The photos go into `files/reports/`, already
stripped of their metadata at upload; thumbnails are not exported, they are made again from the
photo. People are named by the e-mail address that the `members` part of the export already
holds.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from django.core.exceptions import SuspiciousFileOperation

from housecairn.homes import exports
from housecairn.homes.models import Home
from housecairn.reports.models import Report
from housecairn.reports.storage import report_storage
from housecairn.rooms.files import EXTENSIONS


def _archive_name(report: Report) -> str:
    return f"reports/{report.id}{EXTENSIONS.get(report.photo_content_type, '')}"


def _stored_file(report: Report) -> Path | None:
    """The photo on disk, if it is there and inside the folder of its own home."""
    if not report.photo:
        return None
    try:
        path = Path(report_storage.path(report.photo.name)).resolve()
    except (SuspiciousFileOperation, ValueError, OSError):
        return None
    folder = (Path(report_storage.location) / str(report.home_id)).resolve()
    if path.parent != folder or not path.is_file():
        return None
    return path


def _reports(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "status": r.status,
            "place": r.place,
            "room": str(r.room_id) if r.room_id else None,
            "item": str(r.item_id) if r.item_id else None,
            "stock_item": str(r.article_id) if r.article_id else None,
            "task": str(r.task_id) if r.task_id else None,
            "reporter": r.reporter.email if r.reporter else None,
            "file": f"files/{_archive_name(r)}" if _stored_file(r) else None,
            "created_at": r.created_at.isoformat(),
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        }
        for r in Report.objects.filter(home=home)
        .select_related("reporter")
        .order_by("created_at", "id")
    ]


def _files(home: Home) -> Iterator[exports.ExportedFile]:
    for report in Report.objects.filter(home=home).order_by("created_at", "id"):
        source = _stored_file(report)
        if source is not None:
            yield exports.ExportedFile(name=_archive_name(report), source=source)


def register() -> None:
    exports.register("reports", _reports)
    exports.register_files(_files)
