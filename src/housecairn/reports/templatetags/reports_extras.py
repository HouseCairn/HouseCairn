from typing import Any

from django import template

from housecairn.homes import services as home_services
from housecairn.reports import services

register = template.Library()


@register.inclusion_tag("reports/_row.html", takes_context=True)
def reports_row(context: dict[str, Any], home: Any) -> dict[str, Any]:
    """The row of the home page that leads to the reports, with the number waiting."""
    request = context["request"]
    can_write = home_services.can_write(request.user, home)
    return {
        "home": home,
        "waiting": services.open_count(home) if can_write else 0,
        "request": request,
    }


@register.inclusion_tag("reports/_today.html", takes_context=True)
def open_reports_line(context: dict[str, Any], home: Any) -> dict[str, Any]:
    """On Today, one line for the members who write: how many reports wait for them."""
    request = context["request"]
    waiting = services.open_count(home) if home_services.can_write(request.user, home) else 0
    return {"home": home, "waiting": waiting, "request": request}
