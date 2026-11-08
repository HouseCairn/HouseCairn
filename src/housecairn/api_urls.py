"""API v1 routes (docs/adr/0004). Mounted at /api/v1/ with the namespace "api-v1"."""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from housecairn.accounts.api import AccountDeleteView, MeView
from housecairn.events.api import EventCreateView
from housecairn.homes.api import AcceptInvitationView, HomeViewSet, InvitationViewSet, MemberViewSet
from housecairn.instance.api import (
    InstanceAuditView,
    InstanceEmailTestView,
    InstanceInvitationViewSet,
    InstanceProviderCheckView,
    InstanceProvidersView,
    InstanceProviderView,
    InstanceSettingResetView,
    InstanceSettingsView,
    InstanceUsageView,
    UnlockHomesView,
)
from housecairn.labels import api as labels_api
from housecairn.rooms import api as rooms_api
from housecairn.stock import api as stock_api
from housecairn.tasks import api as tasks_api

app_name = "api-v1"

router = SimpleRouter(trailing_slash=True)
router.register("homes", HomeViewSet, basename="home")
router.register(r"homes/(?P<home_id>[0-9a-f-]{36})/members", MemberViewSet, basename="home-member")
router.register(
    r"homes/(?P<home_id>[0-9a-f-]{36})/invitations", InvitationViewSet, basename="home-invitation"
)
router.register(
    r"homes/(?P<home_id>[0-9a-f-]{36})/rooms", rooms_api.RoomViewSet, basename="home-room"
)
router.register(
    r"homes/(?P<home_id>[0-9a-f-]{36})/items", rooms_api.ItemViewSet, basename="home-item"
)
router.register(
    r"homes/(?P<home_id>[0-9a-f-]{36})/photos", rooms_api.PhotoViewSet, basename="home-photo"
)
for prefix, viewset, basename in (
    ("tasks", tasks_api.TaskViewSet, "home-task"),
    ("occurrences", tasks_api.OccurrenceViewSet, "home-occurrence"),
    ("contractors", tasks_api.ContractorViewSet, "home-contractor"),
    ("articles", stock_api.ArticleViewSet, "home-article"),
    ("suppliers", stock_api.SupplierViewSet, "home-supplier"),
    ("movements", stock_api.MovementViewSet, "home-movement"),
    ("attachments", tasks_api.AttachmentViewSet, "home-attachment"),
    ("labels", labels_api.LabelViewSet, "home-label"),
):
    router.register(rf"homes/(?P<home_id>[0-9a-f-]{{36}})/{prefix}", viewset, basename=basename)

router.register("instance/invitations", InstanceInvitationViewSet, basename="instance-invitation")
router.register("instance/audit", InstanceAuditView, basename="instance-audit")

urlpatterns = [
    path("instance/settings/", InstanceSettingsView.as_view(), name="instance-settings"),
    path(
        "instance/settings/email-test/", InstanceEmailTestView.as_view(), name="instance-email-test"
    ),
    path(
        "instance/settings/<slug:key>/",
        InstanceSettingResetView.as_view(),
        name="instance-setting-reset",
    ),
    path("instance/providers/", InstanceProvidersView.as_view(), name="instance-provider-list"),
    path(
        "instance/providers/<slug:slug>/",
        InstanceProviderView.as_view(),
        name="instance-provider-detail",
    ),
    path(
        "instance/provider-check/",
        InstanceProviderCheckView.as_view(),
        name="instance-provider-check",
    ),
    path("instance/unlock/", UnlockHomesView.as_view(), name="instance-unlock"),
    path("instance/usage/", InstanceUsageView.as_view(), name="instance-usage"),
    path("account/delete/", AccountDeleteView.as_view(), name="account-delete"),
    path("me/", MeView.as_view(), name="me"),
    path("me/home/", tasks_api.MyHomeView.as_view(), name="my-home"),
    path(
        "me/display-preferences/", tasks_api.PreferencesView.as_view(), name="display-preferences"
    ),
    path("labels/resolve/<str:code>/", labels_api.LabelResolveView.as_view(), name="label-resolve"),
    path("homes/<uuid:home_id>/today/", tasks_api.TodayView.as_view(), name="home-today"),
    *router.urls,
    path("homes/<uuid:home_id>/events/", EventCreateView.as_view(), name="home-events"),
    path("homes/<uuid:home_id>/search/", rooms_api.SearchView.as_view(), name="home-search"),
    path("invitations/accept/", AcceptInvitationView.as_view(), name="invitation-accept"),
    path("", include("housecairn.notifications.api_urls")),  # docs/adr/0043
]
