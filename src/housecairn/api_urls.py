"""API v1 routes (docs/adr/0004). Mounted at /api/v1/ with the namespace "api-v1"."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from housecairn.events.api import EventCreateView
from housecairn.homes.api import AcceptInvitationView, HomeViewSet, InvitationViewSet, MemberViewSet
from housecairn.rooms import api as rooms_api
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
    ("attachments", tasks_api.AttachmentViewSet, "home-attachment"),
):
    router.register(rf"homes/(?P<home_id>[0-9a-f-]{{36}})/{prefix}", viewset, basename=basename)

urlpatterns = [
    *router.urls,
    path("homes/<uuid:home_id>/events/", EventCreateView.as_view(), name="home-events"),
    path("homes/<uuid:home_id>/search/", rooms_api.SearchView.as_view(), name="home-search"),
    path("invitations/accept/", AcceptInvitationView.as_view(), name="invitation-accept"),
]
