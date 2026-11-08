"""Refresh the settings snapshot at the start of each request (docs/adr/0031)."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from housecairn.instance import config


class SettingsSnapshotMiddleware:
    """Settings a process derives from the database follow it within a few seconds.

    Reading one setting reloads the snapshot when it is old; doing it first thing in the
    request makes the values Django and allauth hold (address verification, security
    alerts) current before any view uses them.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        config.refresh()
        return self.get_response(request)
