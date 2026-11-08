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
]
