"""API routes of the calendar, included in `housecairn.api_urls` (namespace "api-v1")."""

from django.urls import path

from housecairn.calendar import api

urlpatterns = [
    path("calendar/", api.CalendarView.as_view(), name="calendar"),
    path("me/calendar-feeds/", api.FeedListView.as_view(), name="calendar-feed-list"),
    path(
        "me/calendar-feeds/<uuid:feed_id>/",
        api.FeedDetailView.as_view(),
        name="calendar-feed-detail",
    ),
    path(
        "me/calendar-feeds/<uuid:feed_id>/regenerate/",
        api.FeedRegenerateView.as_view(),
        name="calendar-feed-regenerate",
    ),
]
