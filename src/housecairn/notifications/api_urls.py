"""API routes of notifications, included in `housecairn.api_urls` (namespace "api-v1")."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from housecairn.notifications import api

router = SimpleRouter()
router.register("me/notification-channels", api.ChannelViewSet, basename="notification-channel")

urlpatterns = [
    path(
        "me/notification-preferences/",
        api.PreferencesView.as_view(),
        name="notification-preferences",
    ),
    path("me/notifications-export/", api.ExportView.as_view(), name="notification-export"),
    *router.urls,
]
