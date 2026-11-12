"""A refusal of the demonstration mode, on a web screen, becomes a message (docs/adr/0071)."""

from collections.abc import Callable

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme

from housecairn.demo import mode


class DemoRefusalMiddleware:
    """Turns `DemoRefusedError` into the message it carries, back on the same screen.

    The API never gets here: its exception handler answers a 403 with the code `demo`.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse | None:
        if not isinstance(exception, mode.DemoRefusedError) or request.method == "GET":
            return None
        messages.error(request, exception.message)
        # Back to the screen the form was on: an action address (a test button) has no page.
        referer = request.headers.get("Referer", "")
        safe = url_has_allowed_host_and_scheme(
            referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        )
        here = referer if referer and safe else request.get_full_path()
        response = HttpResponseRedirect(here, status=303)
        if request.headers.get("HX-Request"):
            response["HX-Redirect"] = here
        return response
