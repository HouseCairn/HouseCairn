"""Web routes of the calendar and its feeds (docs/adr/0052)."""

from django.urls import path

from housecairn.calendar import views

app_name = "calendar"

urlpatterns = [
    path("", views.IndexView.as_view(), name="index"),
    path("week/", views.WeekView.as_view(), name="week"),
    path("month/", views.MonthView.as_view(), name="month"),
    path("year/", views.YearView.as_view(), name="year"),
    path("feeds/", views.FeedsView.as_view(), name="feeds"),
    path("feeds/<uuid:feed_id>/regenerate/", views.FeedRegenerateView.as_view(), name="regenerate"),
    path("feeds/<uuid:feed_id>/revoke/", views.FeedRevokeView.as_view(), name="revoke"),
    # The secret address: no sign-in, the secret in the path is the credential.
    path("feed/<str:token>.ics", views.feed, name="feed"),
]
