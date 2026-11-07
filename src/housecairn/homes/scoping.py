"""Shared mechanism that limits web and API views to the user's homes."""

from typing import Any
from uuid import UUID

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from rest_framework.request import Request

from housecairn.apitokens.models import ApiToken
from housecairn.homes import services
from housecairn.homes.models import Home


def homes_for_request(request: HttpRequest | Request) -> models.QuerySet[Home]:
    """Homes visible to this request: the user's, narrowed by the API token if any."""
    token = getattr(request, "auth", None)
    restrict_to: list[UUID] | None = None
    if isinstance(token, ApiToken):
        restrict_to = list(token.homes.values_list("id", flat=True))
    return services.homes_for(request.user, restrict_to=restrict_to)


class HomeScopedMixin:
    """For web and API views alike: `get_homes()`, and `get_home()` from the URL.

    A home the user cannot see answers 404, never 403, so its existence does
    not leak.
    """

    request: Any
    kwargs: dict[str, Any]
    home_url_kwarg = "home_id"

    def get_homes(self) -> models.QuerySet[Home]:
        return homes_for_request(self.request)

    def get_home(self) -> Home:
        return get_object_or_404(self.get_homes(), id=self.kwargs[self.home_url_kwarg])


class WebHomeScopedMixin(LoginRequiredMixin, HomeScopedMixin):
    """Web views: sign-in required, then the same scoping as the API."""
