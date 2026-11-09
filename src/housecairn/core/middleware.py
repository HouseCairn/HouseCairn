"""Response headers set for every response, whichever view (or none) produced it."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

# Browser features the application never uses. Photos are sent through a file field,
# which needs no camera permission; nothing reads a position, takes payments or talks to USB.
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


class PermissionsPolicyMiddleware:
    """Add `Permissions-Policy` to every response (defence in depth next to the CSP)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response
