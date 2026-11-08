from typing import Any

from django import template

from housecairn.homes import services as home_services
from housecairn.labels import services
from housecairn.labels.models import Label

register = template.Library()


@register.inclusion_tag("labels/_tools.html", takes_context=True)
def object_tools(context: dict[str, Any], kind: str, target: Any) -> dict[str, Any]:
    """On the page of a room, an item or a stock item: its QR label.

    Every member sees the label; only a member who writes can make one that does not exist.
    """
    request = context["request"]
    home = context["home"]
    label: Label | None = services.active_label_for(target)
    return {
        "home": home,
        "kind": kind,
        "target": target,
        "label": label,
        "can_write": home_services.can_write(request.user, home),
        "request": request,
        "csrf_token": context.get("csrf_token", ""),
    }


@register.inclusion_tag("labels/_row.html")
def labels_row(home: Any) -> dict[str, Any]:
    """The row of the home page that leads to the QR labels."""
    return {"home": home}
