"""Shared mechanism that limits web and API views to the user's homes."""

from typing import Any
from uuid import UUID

from allauth.core import ratelimit
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.utils import translation
from django.utils.translation import gettext as _
from rest_framework import exceptions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import exception_handler

from housecairn.accounts import services as account_services
from housecairn.apitokens.models import ApiToken
from housecairn.homes import emails, services, sso
from housecairn.homes.models import Home, Invitation


def homes_for_request(request: HttpRequest | Request) -> models.QuerySet[Home]:
    """Homes the request's user belongs to, narrowed by the API token if any.

    Includes homes that require a sign-in provider this session did not use:
    lists show them, locked. Anything that reads or changes a home goes
    through `HomeScopedMixin`, which only opens the others.
    """
    token = getattr(request, "auth", None)
    restrict_to: list[UUID] | None = None
    if isinstance(token, ApiToken):
        restrict_to = list(token.homes.values_list("id", flat=True))
    return services.homes_for(request.user, restrict_to=restrict_to)


def open_homes_for_request(request: HttpRequest | Request) -> models.QuerySet[Home]:
    """Homes this request may read and change (docs/adr/0021)."""
    return services.open_homes(homes_for_request(request), sso.signed_in_providers(request))


class HomeScopedMixin:
    """For web and API views alike: `get_homes()`, and `get_home()` from the URL.

    A home the user cannot see answers 404, never 403, so its existence does
    not leak. A home of the user that requires a sign-in provider this session
    did not use raises `SsoRequiredError` (403, with the provider to use).
    """

    request: Any
    kwargs: dict[str, Any]
    home_url_kwarg = "home_id"

    def get_homes(self) -> models.QuerySet[Home]:
        return open_homes_for_request(self.request)

    def get_home(self) -> Home:
        home = get_object_or_404(
            homes_for_request(self.request), id=self.kwargs[self.home_url_kwarg]
        )
        services.check_open(home, sso.signed_in_providers(self.request))
        return home


class WebHomeScopedMixin(LoginRequiredMixin, HomeScopedMixin):
    """Web views: sign-in required, then the same scoping as the API."""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        try:
            response: HttpResponseBase = super().dispatch(request, *args, **kwargs)
            return response
        except services.SsoRequiredError as exc:
            return sso_required_response(request, exc)


def sso_required_response(request: HttpRequest, exc: services.SsoRequiredError) -> HttpResponse:
    provider = sso.provider_named(exc.provider_id, request)
    declared = any(p.id == exc.provider_id for p in sso.declared_providers(request))
    response = TemplateResponse(
        request,
        "homes/sso_required.html",
        {"home": exc.home, "provider": provider, "provider_declared": declared},
        status=403,
    )
    return response.render()


class SsoRequiredApiError(exceptions.PermissionDenied):
    default_code = "sso_required"


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF exception handler: `SsoRequiredError` becomes a 403 naming the provider."""
    if isinstance(exc, services.SsoRequiredError):
        return Response(
            {
                "detail": _("This home requires signing in through %(provider)s.")
                % {"provider": sso.provider_named(exc.provider_id).name},
                "code": "sso_required",
                "provider": exc.provider_id,
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return exception_handler(exc, context)


# ---------- invitations: delivery and rate limits ----------


def site_url(request: HttpRequest | Request) -> str:
    """Scheme and host for links sent away from the site (docs/adr/0020)."""
    configured: str = settings.HOUSECAIRN_SITE_URL
    if configured:
        return configured
    return f"{request.scheme}://{request.get_host()}"


def delivery_for(request: HttpRequest | Request) -> services.Delivery:
    """Send invitations by email when the instance can; otherwise hand the link back."""
    if not account_services.email_is_configured():
        return services.Delivery()
    base = site_url(request)
    language = translation.get_language()

    def send(invitation: Invitation, raw: str) -> None:
        emails.send_invitation(invitation, emails.invitation_link(base, raw), language=language)

    return services.Delivery(send=send)


def invitation_link(request: HttpRequest | Request, raw: str) -> str:
    return emails.invitation_link(site_url(request), raw)


def allow(request: HttpRequest | Request, action: str) -> bool:
    """Consume one use of a rate limit of `ACCOUNT_RATE_LIMITS` (django-allauth).

    The client address is REMOTE_ADDR, set by ForwardedHeadersMiddleware from a
    trusted proxy only (docs/adr/0012).
    """
    django_request = request._request if isinstance(request, Request) else request
    user = request.user if request.user.is_authenticated else None
    return bool(ratelimit.consume(django_request, action=action, user=user))
