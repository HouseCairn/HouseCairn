from django.http import HttpRequest

# Sections of the signed-in navigation, in display order.
HOME, HOMES, MORE = "home", "homes", "more"


def nav_section(request: HttpRequest) -> str:
    """The navigation entry that matches the page being shown ("" on an error page)."""
    match = getattr(request, "resolver_match", None)
    if match is None:
        return ""
    if match.view_name == "index":
        return HOME
    if match.namespace == "homes":
        return HOMES
    return MORE


def shell(request: HttpRequest) -> dict[str, str]:
    """Context of the application shell: which navigation entry is current."""
    return {"nav_section": nav_section(request)}
