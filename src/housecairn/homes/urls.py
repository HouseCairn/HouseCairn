"""Web routes of homes. Stable addresses: /h/<home_id>/... (docs/adr/0010)."""

from django.urls import path

from housecairn.homes import views

app_name = "homes"

urlpatterns = [
    path("", views.HomeListView.as_view(), name="list"),
    path("<uuid:home_id>/", views.HomeDetailView.as_view(), name="detail"),
]
