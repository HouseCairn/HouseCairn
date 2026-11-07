"""API v1 routes (docs/adr/0004). Mounted at /api/v1/ with the namespace "api-v1"."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from housecairn.events.api import EventCreateView
from housecairn.homes.api import HomeViewSet

app_name = "api-v1"

router = SimpleRouter(trailing_slash=True)
router.register("homes", HomeViewSet, basename="home")

urlpatterns = [
    *router.urls,
    path("homes/<uuid:home_id>/events/", EventCreateView.as_view(), name="home-events"),
]
