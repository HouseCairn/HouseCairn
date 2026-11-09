"""`{% tab_bar "tasks" %}`: the tabs of an area of the application (docs/adr/0017).

One component for every sub-navigation, so that the current tab, the horizontal scroll on a
phone, the touch targets and the focus ring are the same everywhere. A group names the
tabs of an area; a tab is shown only to the people who may open it.
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from django import template
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

register = template.Library()


@dataclass(frozen=True)
class Tab:
    label: Any
    url: str
    current: bool


def _home_id(context: template.Context, request: HttpRequest) -> Any:
    home = context.get("home")
    if home is not None and getattr(home, "pk", None):
        return home.pk
    match = getattr(request, "resolver_match", None)
    return match.kwargs.get("home_id") if match else None


def _tasks(context: template.Context, request: HttpRequest, view: str) -> list[Tab]:
    home_id = _home_id(context, request)
    if home_id is None:
        return []
    kwargs = {"home_id": home_id}
    here = request.POST.get("next") or request.GET.get("next") or request.get_full_path()
    if view != "display-preferences":
        here = request.get_full_path()
    return [
        Tab(_("Today"), reverse("tasks:today", kwargs=kwargs), view == "tasks:today"),
        Tab(_("All tasks"), reverse("tasks:list", kwargs=kwargs), view == "tasks:list"),
        Tab(_("History"), reverse("tasks:history", kwargs=kwargs), view == "tasks:history"),
        Tab(_("Projects"), reverse("projects:list", kwargs=kwargs), view.startswith("projects:")),
        Tab(
            _("Contractors"),
            reverse("tasks:contractors", kwargs=kwargs),
            view.startswith("tasks:contractor"),
        ),
        Tab(
            _("Display preferences"),
            f"{reverse('display-preferences')}?next={quote(here, safe='/')}",
            view == "display-preferences",
        ),
    ]


def _home(context: template.Context, request: HttpRequest, view: str) -> list[Tab]:
    home_id = _home_id(context, request)
    if home_id is None:
        return []
    kwargs = {"home_id": home_id}
    tabs = [
        Tab(_("Overview"), reverse("homes:detail", kwargs=kwargs), view == "homes:detail"),
        Tab(
            _("Household and roles"),
            reverse("homes:household", kwargs=kwargs),
            view in ("homes:household", "homes:member"),
        ),
    ]
    if context.get("is_owner") or context.get("role") == "owner":
        tabs.append(
            Tab(_("Audit log"), reverse("homes:audit", kwargs=kwargs), view == "homes:audit")
        )
    return tabs


def _instance(context: template.Context, request: HttpRequest, view: str) -> list[Tab]:
    return [
        Tab(_("Overview"), reverse("instance:overview"), view == "instance:overview"),
        Tab(_("Settings"), reverse("instance:settings"), view == "instance:settings"),
        Tab(
            _("Sign-in providers"),
            reverse("instance:providers"),
            view in ("instance:providers", "instance:provider"),
        ),
        Tab(_("Files of the homes"), reverse("instance:usage"), view == "instance:usage"),
        Tab(_("Audit log"), reverse("instance:audit"), view == "instance:audit"),
    ]


_GROUPS = {
    "tasks": (_("Tasks"), _tasks),
    "home": (_("Home"), _home),
    "instance": (_("Instance administration"), _instance),
}


@register.inclusion_tag("components/tabs.html", takes_context=True)
def tab_bar(context: template.Context, group: str) -> dict[str, Any]:
    label, build = _GROUPS[group]
    request = context["request"]
    match = getattr(request, "resolver_match", None)
    view = match.view_name if match else ""
    return {"label": label, "tabs": build(context, request, view)}
