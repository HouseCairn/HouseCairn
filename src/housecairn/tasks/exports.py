"""Tasks are part of the export of their home (docs/adr/0023, 0031).

Plain objects with identifiers, dates and amounts as text; people are named by the
e-mail address that the `members` part of the export already holds.
"""

from typing import Any

from housecairn.homes import exports
from housecairn.homes.models import Home
from housecairn.tasks.models import Contractor, Occurrence, Task


def _contractors(home: Home) -> list[dict[str, Any]]:
    return [
        {"id": str(c.id), "name": c.name, "trade": c.trade, "note": c.note}
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


def register() -> None:
    exports.register("contractors", _contractors)
    exports.register("tasks", _tasks)
    exports.register("occurrences", _occurrences)
