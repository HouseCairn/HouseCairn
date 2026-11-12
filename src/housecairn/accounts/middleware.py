"""Cookie of a new device, and the answer when the mail server does not take a message."""

from collections.abc import Callable

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from housecairn.accounts.adapters import MailDeliveryError
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


class MailDeliveryMiddleware:
    """A mail server that fails never ends a request in a server error.

    allauth sends mail from many places (password reset, sign-in with an unverified
    address, adding an address, asking for the verification again). `AccountAdapter`
    raises `MailDeliveryError` when the server does not take the message; the sign-up
    page answers it itself (it undoes the account), and security notices never raise it.
    For the others, the page the person was on comes back, with the reason. The same
    answer whatever the address, so that a password reset does not tell a known address
    from an unknown one.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse | None:
        if not isinstance(exception, MailDeliveryError):
            return None
        messages.error(
            request,
            _(
                "The email could not be sent. Try again later, or ask the administrator "
                "to check the outgoing mail settings."
            ),
        )
        return redirect(request.get_full_path())
