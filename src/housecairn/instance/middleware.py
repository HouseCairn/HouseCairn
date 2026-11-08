"""Refresh the settings snapshot at the start of each request (docs/adr/0035), and let the
sign-in forms reach the providers declared in the interface (docs/adr/0041)."""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.middleware.locale import LocaleMiddleware
from django.utils import timezone, translation
from django.utils.translation import trans_real

from housecairn.instance import config, providers


def asked_language(request: HttpRequest) -> str | None:
    """The language the person asks for, by the language cookie or the browser; else None.

    Only a language the instance offers counts, as Django matches it (`fr-CA` gives `fr`).
    """
    cookie = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
    candidates = [cookie] if cookie else []
    header = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    candidates += [code for code, _q in trans_real.parse_accept_lang_header(header) if code != "*"]
    for code in candidates:
        try:
            return translation.get_supported_language_variant(code)
        except LookupError:
            continue
    return None


class InstanceLocaleMiddleware(LocaleMiddleware):
    """Django's language choice, with the instance's default language as the fallback.

    The person's choice wins (cookie, then browser); only a request that asks for no
    language the instance offers gets the default of the instance (docs/adr/0042).
    """

    def process_request(self, request: HttpRequest) -> None:
        language = asked_language(request) or str(config.get_setting("default_language"))
        translation.activate(language)
        request.LANGUAGE_CODE = translation.get_language()


class InstanceTimeZoneMiddleware:
    """Activate the time zone of the instance for the request: dates on pages follow it."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        timezone.activate(config.instance_zone())
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()


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
