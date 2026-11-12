"""A refusal of the demonstration mode, on a web screen, becomes a message (docs/adr/0071)."""

from collections.abc import Callable

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme

from housecairn.demo import admin, mode


class DemoRefusalMiddleware:
    """Turns `DemoRefusedError` into the message it carries, back on the same screen.

    The API never gets here: its exception handler answers a 403 with the code `demo`.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_view(
        self,
        request: HttpRequest,
        view_func: Callable[..., HttpResponse],
        view_args: tuple[object, ...],
        view_kwargs: dict[str, object],
    ) -> HttpResponse | None:
        """The administration site is read only: anything but a read is refused (demo.admin)."""
        match = request.resolver_match
        if (
            mode.is_on()
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and match is not None
            and "admin" in match.namespaces
            and match.url_name not in admin.ALLOWED_URL_NAMES
        ):
            return self._back(request, admin.admin_message())
        return None

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse | None:
        if not isinstance(exception, mode.DemoRefusedError) or request.method == "GET":
            return None
        return self._back(request, exception.message)

    def _back(self, request: HttpRequest, message: str) -> HttpResponse:
        messages.error(request, message)
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
