"""Web/API parity registry (docs/adr/0003).

Every named web route maps to the API route that offers the same function, or
is listed in EXEMPT with the reason it has no API counterpart. The test
`tests/test_parity.py` fails when a web route is in neither.
"""

from collections.abc import Iterator

from django.urls import URLPattern, URLResolver, get_resolver

# Web route name -> API route name(s).
PARITY: dict[str, tuple[str, ...]] = {
    "homes:list": ("api-v1:home-list",),
    "homes:create": ("api-v1:home-list",),
    "homes:detail": ("api-v1:home-detail",),
    "homes:household": ("api-v1:home-member-list", "api-v1:home-invitation-list"),
    "homes:invite": ("api-v1:home-invitation-list",),
    "homes:invitation-resend": ("api-v1:home-invitation-resend",),
    "homes:invitation-revoke": ("api-v1:home-invitation-detail",),
    "homes:required-provider": ("api-v1:home-detail",),
    "homes:leave": ("api-v1:home-leave",),
    "homes:member": ("api-v1:home-member-detail",),
    "homes:member-role": ("api-v1:home-member-detail",),
    "homes:member-remove": ("api-v1:home-member-detail",),
    "homes:transfer": ("api-v1:home-member-make-owner",),
    # Creating an account from an invitation is account management, which the
    # API leaves to sign-in (see EXEMPT_MODULE_PREFIXES); accepting is in it.
    "invitation": ("api-v1:invitation-accept",),
    # Rooms, items and photos (docs/adr/0029, 0030). The entry page only leads to
    # the rooms of a home: choosing among the homes is the list of homes.
    "rooms": ("api-v1:home-list",),
    "rooms:list": ("api-v1:home-room-list",),
    "rooms:create": ("api-v1:home-room-list",),
    "rooms:detail": ("api-v1:home-room-detail",),
    "rooms:edit": ("api-v1:home-room-detail",),
    "rooms:memory": ("api-v1:home-room-detail",),
    "rooms:delete": ("api-v1:home-room-detail",),
    "rooms:move": ("api-v1:home-room-reorder",),
    "rooms:item-create": ("api-v1:home-item-list",),
    "rooms:item-detail": ("api-v1:home-item-detail",),
    "rooms:item-edit": ("api-v1:home-item-detail",),
    "rooms:item-delete": ("api-v1:home-item-detail",),
    "rooms:room-photo-add": ("api-v1:home-photo-list",),
    "rooms:item-photo-add": ("api-v1:home-photo-list",),
    "rooms:photo": ("api-v1:home-photo-content",),
    "rooms:photo-thumbnail": ("api-v1:home-photo-thumbnail",),
    "rooms:photo-delete": ("api-v1:home-photo-detail",),
    "rooms:search": ("api-v1:home-search",),
}

# Web routes without business function, with the reason.
EXEMPT: dict[str, str] = {
    "index": "landing page, no data",
    "healthz": "probe for the container runtime",
    "api-schema": "API description itself",
    "api-docs": "API documentation page",
    "manifest": "web app manifest read by browsers",
    "more": "navigation page that links to other screens",
    "about": "static information page",
}

# Third-party route trees: sign-in, administration. Their functions are either
# account management, which the API does not expose to tokens, or operator tools.
EXEMPT_NAMESPACES: frozenset[str] = frozenset({"admin", "api-v1"})
EXEMPT_MODULE_PREFIXES: tuple[str, ...] = ("allauth.",)


def _walk(
    patterns: list[URLPattern | URLResolver], namespace: str = ""
) -> Iterator[tuple[str, str]]:
    for entry in patterns:
        if isinstance(entry, URLResolver):
            ns = entry.namespace or ""
            full = f"{namespace}:{ns}" if namespace and ns else (ns or namespace)
            yield from _walk(entry.url_patterns, full)
        elif entry.name:
            name = f"{namespace}:{entry.name}" if namespace else entry.name
            module = getattr(entry.callback, "__module__", "") or ""
            yield name, module


def all_routes() -> dict[str, str]:
    """Every named route, with the module of its view."""
    return dict(_walk(get_resolver().url_patterns))


def web_routes() -> set[str]:
    routes = set()
    for name, module in all_routes().items():
        if name.split(":", 1)[0] in EXEMPT_NAMESPACES and ":" in name:
            continue
        if module.startswith(EXEMPT_MODULE_PREFIXES):
            continue
        routes.add(name)
    return routes


def missing_api_counterparts() -> list[str]:
    """Web routes neither mapped to the API nor exempted."""
    return sorted(r for r in web_routes() if r not in PARITY and r not in EXEMPT)


def unknown_api_routes() -> list[str]:
    """API names in PARITY that do not exist."""
    names = set(all_routes())
    return sorted(api for apis in PARITY.values() for api in apis if api not in names)
