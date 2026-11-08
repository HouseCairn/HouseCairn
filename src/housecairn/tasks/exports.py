"""Tasks are part of the export of their home (docs/adr/0023, 0031, 0034).

Plain objects with identifiers, dates and amounts as text; people are named by the
e-mail address that the `members` part of the export already holds. The files of the
attachments go into `files/attachments/`, as they are stored: images already stripped
of their metadata at upload (docs/adr/0030), documents untouched. Thumbnails are not
exported, they are made again from the image.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from django.core.exceptions import SuspiciousFileOperation
from django.db import models

from housecairn.homes import exports
from housecairn.homes.models import Home
from housecairn.tasks.models import Attachment, Contractor, Occurrence, Task
from housecairn.tasks.storage import attachment_storage


def _contractors(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "trade": c.trade,
            "trade_other": c.trade_other,
            "phone": c.phone,
            "email": c.email,
            "address": c.address,
            "note": c.note,
        }
        for c in Contractor.objects.filter(home=home).order_by("created_at", "id")
    ]


def _tasks(home: Home) -> list[dict[str, Any]]:
    rows = Task.objects.filter(home=home).select_related("assignee").order_by("created_at", "id")
    return [
        {
            "id": str(t.id),
            "title": t.title,
            "room": str(t.room_id) if t.room_id else None,
            "item": str(t.item_id) if t.item_id else None,
            "priority": t.priority,
            "estimated_minutes": t.estimated_minutes,
            "labour_budget": str(t.labour_budget) if t.labour_budget is not None else None,
            "material_budget": str(t.material_budget) if t.material_budget is not None else None,
            "notes": t.notes,
            "procedure": t.procedure,
            "assignee": t.assignee.email if t.assignee else None,
            "contractor": str(t.contractor_id) if t.contractor_id else None,
            "repeat_mode": t.repeat_mode,
            "repeat_unit": t.repeat_unit,
            "repeat_interval": t.repeat_interval,
            "season": t.season,
            "season_start_month": t.season_start_month,
            "season_end_month": t.season_end_month,
            "hide_days_before": t.hide_days_before,
            "created_at": t.created_at.isoformat(),
        }
        for t in rows
    ]


def _occurrences(home: Home) -> list[dict[str, Any]]:
    rows = (
        Occurrence.objects.filter(home=home, task__deleted_at__isnull=True)
        .select_related("completed_by")
        .order_by("created_at", "id")
    )
    return [
        {
            "id": str(o.id),
            "task": str(o.task_id),
            "status": o.status,
            "due_on": o.due_on.isoformat() if o.due_on else None,
            "postponed_from": o.postponed_from.isoformat() if o.postponed_from else None,
            "completed_on": o.completed_on.isoformat() if o.completed_on else None,
            "completed_by": o.completed_by.email if o.completed_by else None,
            "actual_cost": str(o.actual_cost) if o.actual_cost is not None else None,
            "note": o.completion_note,
            "created_at": o.created_at.isoformat(),
        }
        for o in rows
    ]


def _attachment_rows(home: Home) -> models.QuerySet[Attachment]:
    return Attachment.objects.filter(home=home, task__deleted_at__isnull=True).order_by(
        "created_at", "id"
    )


def _archive_name(attachment: Attachment) -> str:
    return f"attachments/{attachment.id}{Path(attachment.file.name).suffix}"


def _stored_file(attachment: Attachment) -> Path | None:
    """The file on disk, if it is there and inside the folder of its own home."""
    try:
        path = Path(attachment_storage.path(attachment.file.name)).resolve()
    except (SuspiciousFileOperation, ValueError, OSError):
        return None
    folder = (Path(attachment_storage.location) / str(attachment.home_id)).resolve()
    if path.parent != folder or not path.is_file():
        return None
    return path


def _attachments(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(a.id),
            "task": str(a.task_id),
            "occurrence": str(a.occurrence_id) if a.occurrence_id else None,
            "name": a.name,
            "content_type": a.content_type,
            "is_image": a.is_image,
            "size_bytes": a.size_bytes,
            "width": a.width,
            "height": a.height,
            "file": f"files/{_archive_name(a)}" if _stored_file(a) else None,
            "created_at": a.created_at.isoformat(),
        }
        for a in _attachment_rows(home)
    ]


def _files(home: Home) -> Iterator[exports.ExportedFile]:
    for attachment in _attachment_rows(home):
        source = _stored_file(attachment)
        if source is not None:
            yield exports.ExportedFile(name=_archive_name(attachment), source=source)


def register() -> None:
    exports.register("contractors", _contractors)
    exports.register("tasks", _tasks)
    exports.register("occurrences", _occurrences)
    exports.register("attachments", _attachments)
    exports.register_files(_files)
