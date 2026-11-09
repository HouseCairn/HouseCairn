from decimal import Decimal
from typing import Any

from django import template
from django.utils.formats import number_format

from housecairn.projects import services
from housecairn.tasks.models import Task

register = template.Library()


@register.filter
def money(amount: Decimal | None, currency: str = "") -> str:
    """An amount as people read it: `1 250,50 EUR`, exact (a `Decimal`, never a float)."""
    if amount is None:
        return ""
    text = number_format(amount, decimal_pos=2, use_l10n=True, force_grouping=True)
    return f"{text}\u00a0{currency}".strip()


@register.inclusion_tag("projects/_gap.html")
def budget_gap(amounts: services.Amounts, currency: str) -> dict[str, Any]:
    """What the budget says, in words: left, over, or on budget. Never by colour alone."""
    return {"amounts": amounts, "currency": currency}


@register.inclusion_tag("projects/_task_link.html", takes_context=True)
def task_project(context: template.Context, task: Task, home: Any) -> dict[str, Any]:
    """The project a task belongs to, as one line of the page of the task (docs/adr/0050)."""
    return {
        "project": services.project_of_task(task),
        "home": home,
        "request": context["request"],
    }
