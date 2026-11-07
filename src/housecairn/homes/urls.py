"""Web routes of homes. Stable addresses: /h/<home_id>/... (docs/adr/0010)."""

from django.urls import path

from housecairn.homes import views

app_name = "homes"

urlpatterns = [
    path("", views.HomeListView.as_view(), name="list"),
    path("new/", views.HomeCreateView.as_view(), name="create"),
    path("<uuid:home_id>/", views.HomeDetailView.as_view(), name="detail"),
    path("<uuid:home_id>/household/", views.HouseholdView.as_view(), name="household"),
    path("<uuid:home_id>/household/invite/", views.InviteView.as_view(), name="invite"),
    path(
        "<uuid:home_id>/household/sign-in/",
        views.RequiredProviderView.as_view(),
        name="required-provider",
    ),
    path("<uuid:home_id>/household/leave/", views.LeaveView.as_view(), name="leave"),
    path(
        "<uuid:home_id>/household/members/<uuid:member_id>/",
        views.MemberView.as_view(),
        name="member",
    ),
    path(
        "<uuid:home_id>/household/members/<uuid:member_id>/role/",
        views.MemberRoleView.as_view(),
        name="member-role",
    ),
    path(
        "<uuid:home_id>/household/members/<uuid:member_id>/remove/",
        views.MemberRemoveView.as_view(),
        name="member-remove",
    ),
    path(
        "<uuid:home_id>/household/members/<uuid:member_id>/make-owner/",
        views.TransferView.as_view(),
        name="transfer",
    ),
    path(
        "<uuid:home_id>/household/invitations/<uuid:invitation_id>/resend/",
        views.InvitationResendView.as_view(),
        name="invitation-resend",
    ),
    path(
        "<uuid:home_id>/household/invitations/<uuid:invitation_id>/revoke/",
        views.InvitationRevokeView.as_view(),
        name="invitation-revoke",
    ),
]
