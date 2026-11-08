"""API of notifications: the caller's channels and reminder preferences (docs/adr/0043).

Same rules as the web, through `services`. An API token reaches these endpoints only with
the `write` scope (a `read` token reads nothing here, an `events` token nothing at all):
a channel makes the server send messages, which reading must not allow.
"""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from housecairn.apitokens.models import ApiToken, Scope
from housecairn.apitokens.permissions import TokenScopePermission
from housecairn.notifications import services
from housecairn.notifications.models import Channel, Preference


class WriteTokenOnly(permissions.BasePermission):
    message = "This token does not have the scope this request needs."

    def has_permission(self, request: Request, view: Any) -> bool:
        token = request.auth
        return not isinstance(token, ApiToken) or token.has_scope(Scope.WRITE)


# The default checks as well: a token also needs `read` to read.
PERMISSIONS = [permissions.IsAuthenticated, TokenScopePermission, WriteTokenOnly]


def _invalid(exc: DjangoValidationError) -> exceptions.ValidationError:
    if hasattr(exc, "error_dict"):
        return exceptions.ValidationError(exc.message_dict)
    return exceptions.ValidationError({"detail": exc.messages})


class ChannelSerializer(serializers.ModelSerializer[Channel]):
    url = serializers.CharField(
        write_only=True,
        max_length=2000,
        help_text="Apprise address, such as `ntfys://ntfy.sh/topic`. Never returned.",
    )

    class Meta:
        model = Channel
        fields = ["id", "name", "url", "scheme", "service", "enabled", "created_at"]
        read_only_fields = ["id", "scheme", "service", "created_at"]


class ChannelUpdateSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=60, required=False)
    enabled = serializers.BooleanField(required=False)


class TestSerializer(serializers.Serializer[Any]):
    ok = serializers.BooleanField()
    detail = serializers.CharField(help_text="One of two fixed sentences.")


class ChannelViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[Channel],
):
    serializer_class = ChannelSerializer
    pagination_class = None
    permission_classes = PERMISSIONS

    def get_queryset(self) -> Any:
        return services.channels_of(self.request.user)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ChannelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            channel = services.add_channel(
                request.user,
                name=serializer.validated_data["name"],
                url=serializer.validated_data["url"],
            )
        except DjangoValidationError as exc:
            raise _invalid(exc) from None
        return Response(ChannelSerializer(channel).data, status=201)

    @extend_schema(request=ChannelUpdateSerializer, responses=ChannelSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        channel = self.get_object()
        serializer = ChannelUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.update_channel(request.user, channel, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise _invalid(exc) from None
        return Response(ChannelSerializer(channel).data)

    def perform_destroy(self, instance: Channel) -> None:
        services.delete_channel(self.request.user, instance)

    @extend_schema(request=None, responses=TestSerializer)
    @action(detail=True, methods=["post"])
    def test(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Send a real test message. The answer never carries the service's own."""
        channel = self.get_object()
        try:
            ok = services.test_channel(request.user, channel)
        except DjangoValidationError as exc:
            raise _invalid(exc) from None
        return Response({"ok": ok, "detail": str(services.TEST_RESULTS[ok])})


class PreferenceSerializer(serializers.ModelSerializer[Preference]):
    class Meta:
        model = Preference
        fields = sorted(services.PREFERENCE_FIELDS)


class PreferencesView(APIView):
    """When the caller wants reminders: delay, time, quiet hours, summary, language."""

    permission_classes = PERMISSIONS

    @extend_schema(responses=PreferenceSerializer)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(PreferenceSerializer(services.preferences_of(request.user)).data)  # type: ignore[arg-type]

    @extend_schema(request=PreferenceSerializer, responses=PreferenceSerializer)
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        current = services.preferences_of(request.user)  # type: ignore[arg-type]
        serializer = PreferenceSerializer(current, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            prefs = services.update_preferences(request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise _invalid(exc) from None
        return Response(PreferenceSerializer(prefs).data)


class ExportSerializer(serializers.Serializer[Any]):
    channels = serializers.ListField(
        child=serializers.DictField(), help_text="Name, scheme, service: never the address."
    )
    preferences = serializers.DictField()


class ExportView(APIView):
    """What the account keeps for notifications, without any channel address."""

    permission_classes = PERMISSIONS

    @extend_schema(responses=ExportSerializer)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(services.export_of(request.user))
