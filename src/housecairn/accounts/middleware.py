"""Sets the cookie of a device new to the account, once its sign-in is recorded."""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from housecairn.accounts.services import DEVICE_COOKIE, DEVICE_COOKIE_MAX_AGE


class DeviceCookieMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        secret = getattr(request, "housecairn_new_device", None)
        if secret:
            response.set_cookie(
                DEVICE_COOKIE,
                secret,
                max_age=DEVICE_COOKIE_MAX_AGE,
                secure=settings.SESSION_COOKIE_SECURE,
                httponly=True,
                samesite="Lax",
            )
        return response
