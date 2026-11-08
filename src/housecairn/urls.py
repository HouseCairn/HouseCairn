"""Root URLs. Address conventions are in docs/adr/0010."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView

from housecairn.accounts import views as account_views
from housecairn.core import views as core_views
from housecairn.homes import views as home_views
from housecairn.instance import views as instance_views
from housecairn.rooms import views as room_views
from housecairn.stock import views as stock_views
from housecairn.tasks import views as task_views

urlpatterns = [
    path("", core_views.IndexView.as_view(), name="index"),
    path("healthz", core_views.healthz, name="healthz"),
    path("manifest.webmanifest", core_views.manifest, name="manifest"),
    path("more/", core_views.MoreView.as_view(), name="more"),
    path("about/", core_views.AboutView.as_view(), name="about"),
    path("h/", include("housecairn.homes.urls")),
    # Rooms, items and photos of a home (docs/adr/0029); /rooms/ is the navigation entry.
    path("h/<uuid:home_id>/", include("housecairn.rooms.urls")),
    path("rooms/", room_views.EntryView.as_view(), name="rooms"),
    # Tasks of a home (docs/adr/0031); /tasks/ is the navigation entry.
    path("h/<uuid:home_id>/", include("housecairn.tasks.urls")),
    path("tasks/", task_views.EntryView.as_view(), name="tasks"),
    # My home (what concerns the person, in every home) and their display preferences
    # (docs/adr/0037).
    path("me/", task_views.MyHomeView.as_view(), name="my-home"),
    path(
        "me/preferences/",
        task_views.PreferencesView.as_view(),
        name="display-preferences",
    ),
    # Stock items, suppliers and movements of a home (docs/adr/0038); /stock/ is the entry.
    path("h/<uuid:home_id>/", include("housecairn.stock.urls")),
    path("stock/", stock_views.EntryView.as_view(), name="stock"),
    # Invitation links, opened signed in or not (docs/adr/0020).
    path("invitations/<str:token>/", home_views.InvitationView.as_view(), name="invitation"),
    # Instance invitation links: an account, without a home (docs/adr/0022).
    path(
        "join/<str:token>/",
        instance_views.InstanceInvitationView.as_view(),
        name="instance-invitation",
    ),
    path("instance/", include("housecairn.instance.urls")),
    # Password reset sends an email: no page without an outgoing mail server.
    # These patterns come first and carry no name, so allauth's own names still
    # reverse to the same addresses.
    path("accounts/delete/", account_views.AccountDeleteView.as_view(), name="account_delete"),
    # Sign-up carries the anti-robot check (docs/adr/0024); same address, allauth's name.
    path("accounts/signup/", account_views.SignupView.as_view()),
    # Adding an address sends it a verification: no page without an outgoing mail server.
    path("accounts/email/", account_views.email_addresses),
    path("accounts/password/reset/", account_views.password_reset),
    path("accounts/password/reset/done/", account_views.password_reset_done),
    path("accounts/", include("allauth.urls")),
    path("admin/", admin.site.urls),
    path("api/v1/", include("housecairn.api_urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "api/docs/",
        SpectacularSwaggerSplitView.as_view(
            url_name="api-schema", template_name="api/swagger_ui.html"
        ),
        name="api-docs",
    ),
]
