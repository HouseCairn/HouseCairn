"""Context of the application shell: the five sections of the navigation (docs/adr/0017).

The bar at the bottom of a phone and the column on the left of a computer carry the same
sections, Today, Rooms, Projects, Budget and More. The entry marked as current follows
the tree of the application: a page belongs to the section whose root leads to it.
"""

from typing import Any
from urllib.parse import urlsplit

from django.http import HttpRequest
from django.urls import Resolver404, ResolverMatch, resolve, reverse

from housecairn.core import more, navigation

# Sections of the signed-in navigation, in display order.
TODAY, ROOMS, PROJECTS, BUDGET, MORE = "today", "rooms", "projects", "budget", "more"

# Pages of an application namespace that belong to More rather than to its section:
# the contractors of a home (More, Home), the display preferences and the calendar
# feeds of the person (More, Me).
_IN_MORE = ("tasks:contractor", "calendar:feeds", "calendar:regenerate", "calendar:revoke")


def nav_section(request: HttpRequest) -> str:
    """The navigation entry that matches the page being shown ("" on an error page).

    With a safe `next`, the section is that of the origin: a room opened from the budget
    keeps Budget marked, so the bar never changes tab under the finger (design guide,
    "Back link and breadcrumbs").
    """
    match = getattr(request, "resolver_match", None)
    if match is None:
        return ""
    origin = navigation.safe_next(request)
    if origin is not None:
        try:
            return _section_of(resolve(urlsplit(origin).path))
        except Resolver404:
            pass
    return _section_of(match)


def _section_of(match: ResolverMatch) -> str:
    """The section a route belongs to, in the tree of the application."""
    view = match.view_name
    if view.startswith(_IN_MORE):
        return MORE
    if view in ("index", "my-home", "tasks") or match.namespace in ("tasks", "calendar"):
        return TODAY
    if match.namespace in ("rooms", "stock") or view in ("rooms", "stock"):
        return ROOMS
    if match.namespace == "projects" or view == "projects":
        return PROJECTS
    if match.namespace == "budget" or view == "budget":
        return BUDGET
    return MORE


def _home_id(request: HttpRequest) -> Any:
    """The home in the address of the page, if it has one."""
    match = getattr(request, "resolver_match", None)
    return match.kwargs.get("home_id") if match else None


def _entry(request: HttpRequest, route: str, entry: str) -> str:
    """The root of a section in the home being viewed, else its entry page."""
    home_id = _home_id(request)
    if home_id:
        return reverse(route, kwargs={"home_id": home_id})
    return reverse(entry)


def today_url(request: HttpRequest) -> str:
    """Address of the Today entry: Today in the home being viewed, else My home."""
    home_id = _home_id(request)
    if home_id:
        return reverse("tasks:today", kwargs={"home_id": home_id})
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return reverse("my-home")
    return reverse("index")


def rooms_url(request: HttpRequest) -> str:
    """Address of the Rooms entry: the rooms of the home being viewed, else the entry page."""
    return _entry(request, "rooms:list", "rooms")


def projects_url(request: HttpRequest) -> str:
    """Address of the Projects entry: the projects of the home being viewed, else the entry."""
    return _entry(request, "projects:list", "projects")


def budget_url(request: HttpRequest) -> str:
    """Address of the Budget entry: the budget of the home being viewed, else the entry."""
    return _entry(request, "budget:overview", "budget")


def stock_url(request: HttpRequest) -> str:
    """Address of the stock (a tab of Rooms): that of the home being viewed, else the entry."""
    return _entry(request, "stock:list", "stock")


def more_groups(request: HttpRequest) -> list[dict[str, Any]]:
    """The content of More, unfolded in the column of a computer (signed in only)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return []
    match = getattr(request, "resolver_match", None)
    return more.for_page(user, _home_id(request), match.view_name if match else "")


def shell(request: HttpRequest) -> dict[str, Any]:
    """Context of the application shell: the current section and the entry addresses."""
    return {
        "nav_more": more_groups(request),
        "nav_section": nav_section(request),
        "today_url": today_url(request),
        "rooms_url": rooms_url(request),
        "projects_url": projects_url(request),
        "budget_url": budget_url(request),
        "stock_url": stock_url(request),
    }
