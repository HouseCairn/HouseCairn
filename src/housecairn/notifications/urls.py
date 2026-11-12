from django.urls import path

from housecairn.notifications import views

app_name = "notifications"

urlpatterns = [
    path("", views.IndexView.as_view(), name="index"),
    path("channels/", views.AddView.as_view(), name="add"),
    path("channels/<uuid:channel_id>/", views.ChannelView.as_view(), name="channel"),
    path("channels/<uuid:channel_id>/test/", views.TestView.as_view(), name="test"),
    path("channels/<uuid:channel_id>/delete/", views.DeleteView.as_view(), name="delete"),
    path("devices/<uuid:device_id>/", views.DeviceView.as_view(), name="device"),
    path("devices/<uuid:device_id>/test/", views.DeviceTestView.as_view(), name="device-test"),
    path(
        "devices/<uuid:device_id>/delete/", views.DeviceDeleteView.as_view(), name="device-delete"
    ),
    path("preferences/", views.PreferencesView.as_view(), name="preferences"),
    path("export/", views.ExportView.as_view(), name="export"),
]
