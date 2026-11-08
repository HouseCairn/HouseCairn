"""Refresh the settings snapshot at the start of each request (docs/adr/0035), and let the
sign-in forms reach the providers declared in the interface (docs/adr/0041)."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from housecairn.instance import config, providers


class SettingsSnapshotMiddleware:
    """Settings a process derives from the database follow it within a few seconds.

    Reading one setting reloads the snapshot when it is old; doing it first thing in the
    request makes the values Django and allauth hold (address verification, security
    alerts) current before any view uses them.

    On the way out, a page gets the origins of the enabled providers of the interface in
    its `form-action`: the browser applies that directive to the redirect that follows
    the sign-in button. Only those origins are added, never a wildcard; the provider set
    by variables is in the static policy (settings.py).
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        config.refresh()
        response = self.get_response(request)
        if response.get("Content-Type", "").startswith("text/html"):
            origins = providers.form_action_origins()
            if origins:
                update = dict(getattr(response, "_csp_update", None) or {})
                update["form-action"] = [*update.get("form-action", []), *origins]
                response._csp_update = update  # type: ignore[attr-defined]
        return response
