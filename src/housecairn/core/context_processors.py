from django.http import HttpRequest
from django.urls import reverse

# Sections of the signed-in navigation, in display order.
HOME, HOMES, ROOMS, TASKS, MORE = "home", "homes", "rooms", "tasks", "more"


def nav_section(request: HttpRequest) -> str:
    """The navigation entry that matches the page being shown ("" on an error page)."""
    match = getattr(request, "resolver_match", None)
    if match is None:
        return ""
    if match.view_name in ("index", "my-home", "display-preferences"):
        return HOME
    if match.namespace == "homes":
        return HOMES
    if match.namespace == "rooms" or match.view_name == "rooms":
        return ROOMS
    if match.namespace == "tasks" or match.view_name == "tasks":
        return TASKS
    return MORE


def rooms_url(request: HttpRequest) -> str:
    """Address of the Rooms entry: the rooms of the home being viewed, else the entry page."""
    match = getattr(request, "resolver_match", None)
    home_id = match.kwargs.get("home_id") if match else None
    if home_id:
        return reverse("rooms:list", kwargs={"home_id": home_id})
    return reverse("rooms")


def tasks_url(request: HttpRequest) -> str:
    """Address of the Tasks entry: the tasks of the home being viewed, else the entry page."""
    match = getattr(request, "resolver_match", None)
    home_id = match.kwargs.get("home_id") if match else None
    if home_id:
        return reverse("tasks:list", kwargs={"home_id": home_id})
    return reverse("tasks")


def home_url(request: HttpRequest) -> str:
    """Address of the Home entry: My home when signed in, else the start page."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return reverse("my-home")
    return reverse("index")


def shell(request: HttpRequest) -> dict[str, str]:
    """Context of the application shell: the current navigation entry and its entry addresses."""
    return {
        "nav_section": nav_section(request),
        "rooms_url": rooms_url(request),
        "tasks_url": tasks_url(request),
        "home_url": home_url(request),
    }
