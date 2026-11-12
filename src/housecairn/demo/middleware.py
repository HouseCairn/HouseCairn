"""A refusal of the demonstration mode, on a web screen, becomes a message (docs/adr/0071)."""

from collections.abc import Callable

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

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
        here = request.get_full_path()
        response = HttpResponseRedirect(here, status=303)
        if request.headers.get("HX-Request"):
            response["HX-Redirect"] = here
        return response
