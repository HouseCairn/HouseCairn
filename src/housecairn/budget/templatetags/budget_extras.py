from decimal import Decimal
from typing import Any

from django import template

from housecairn.budget import services
from housecairn.projects.models import ZERO
from housecairn.projects.services import Amounts
from housecairn.tasks.models import Occurrence, Task

register = template.Library()


@register.inclusion_tag("budget/_gauge.html")
def gauge(amounts: Amounts) -> dict[str, Any]:
    """Engaged against planned, as a labelled gauge. The words carry the meaning, not the bar."""
    if amounts.planned <= ZERO:
        return {"percent": None, "amounts": amounts}
    percent = int((amounts.engaged * 100 / amounts.planned).quantize(Decimal(1)))
    return {"percent": percent, "shown": min(percent, 100), "amounts": amounts}


@register.inclusion_tag("budget/_task_cost.html")
def task_cost(task: Task, home: Any) -> dict[str, Any]:
    """The cost of a task on its page: the estimate, what it comes to in a year, what it cost."""
    row = services.task_row(task)
    if row is None:  # a task of a project: its money is in the budget lines of the project
        return {"row": None}
    total = row.figures(services.anytime)
    return {"row": row, "home": home, "paid": total.paid, "missing": total.missing}


@register.inclusion_tag("budget/_occurrence_cost.html")
def occurrence_cost(occurrence: Occurrence, home: Any) -> dict[str, Any]:
    """On the page of what was done: the estimate, next to the field of the real cost."""
    task = occurrence.task
    parts = [task.labour_budget, task.material_budget]
    estimate = (
        None if all(part is None for part in parts) else sum((p or ZERO for p in parts), ZERO)
    )
    return {"estimate": estimate, "home": home}
