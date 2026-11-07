"""Root URLs. Address conventions are in docs/adr/0010."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView

from housecairn.accounts import views as account_views
from housecairn.core import views as core_views

urlpatterns = [
    path("", core_views.IndexView.as_view(), name="index"),
    path("healthz", core_views.healthz, name="healthz"),
    path("manifest.webmanifest", core_views.manifest, name="manifest"),
    path("more/", core_views.MoreView.as_view(), name="more"),
    path("about/", core_views.AboutView.as_view(), name="about"),
    path("h/", include("housecairn.homes.urls")),
    # Password reset sends an email: no page without an outgoing mail server.
    # These patterns come first and carry no name, so allauth's own names still
    # reverse to the same addresses.
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
