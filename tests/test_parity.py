"""Every web function has its API counterpart (docs/adr/0003)."""

from django.http import HttpRequest, HttpResponse
from django.test import override_settings
from django.urls import include, path

from housecairn import parity


def test_every_web_route_has_an_api_counterpart() -> None:
    assert parity.missing_api_counterparts() == []


def test_declared_api_routes_exist() -> None:
    assert parity.unknown_api_routes() == []


def test_registry_covers_the_first_routes() -> None:
    assert parity.web_routes() >= {"homes:list", "homes:detail"}


def _orphan(request: HttpRequest) -> HttpResponse:
    return HttpResponse()


urlpatterns = [
    path("", include("housecairn.urls")),
    path("orphan/", _orphan, name="orphan"),
]


@override_settings(ROOT_URLCONF=__name__)
def test_a_web_route_without_api_counterpart_is_reported() -> None:
    assert parity.missing_api_counterparts() == ["orphan"]
