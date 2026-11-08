from django.urls import path

from housecairn.notifications import views

app_name = "notifications"

urlpatterns = [
    path("", views.IndexView.as_view(), name="index"),
    path("channels/", views.AddView.as_view(), name="add"),
    path("channels/<uuid:channel_id>/", views.ChannelView.as_view(), name="channel"),
    path("channels/<uuid:channel_id>/test/", views.TestView.as_view(), name="test"),
    path("channels/<uuid:channel_id>/delete/", views.DeleteView.as_view(), name="delete"),
    path("preferences/", views.PreferencesView.as_view(), name="preferences"),
    path("export/", views.ExportView.as_view(), name="export"),
]
