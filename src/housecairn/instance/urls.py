"""Web routes of the instance administrator: /instance/... (docs/adr/0022)."""

from django.urls import path

from housecairn.instance import views

app_name = "instance"

urlpatterns = [
    path("", views.OverviewView.as_view(), name="overview"),
    path("invite/", views.InviteView.as_view(), name="invite"),
    path(
        "invitations/<uuid:invitation_id>/resend/",
        views.ResendView.as_view(),
        name="invitation-resend",
    ),
    path(
        "invitations/<uuid:invitation_id>/revoke/",
        views.RevokeView.as_view(),
        name="invitation-revoke",
    ),
    path("unlock/", views.UnlockView.as_view(), name="unlock"),
    path("audit/", views.AuditView.as_view(), name="audit"),
    path("usage/", views.UsageView.as_view(), name="usage"),
    # One name for the index and the sub-pages: they are one screen to the tabs and the help.
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("settings/<slug:section>/", views.SettingsSectionView.as_view(), name="settings"),
    path("providers/", views.ProvidersView.as_view(), name="providers"),
    path("providers/<slug:slug>/", views.ProviderView.as_view(), name="provider"),
]
