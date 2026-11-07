"""Guards on allauth views that need outgoing email (docs/adr/0007)."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from allauth.account import views as allauth_views
from django.http import Http404, HttpRequest, HttpResponse

from housecairn.accounts import services


def needs_email(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Answer 404 when the instance cannot send email, otherwise run the view."""

    @wraps(view)
    def guarded(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not services.email_is_configured():
            raise Http404("Outgoing email is not configured.")
        return view(request, *args, **kwargs)

    return guarded


password_reset = needs_email(allauth_views.password_reset)
password_reset_done = needs_email(allauth_views.password_reset_done)
