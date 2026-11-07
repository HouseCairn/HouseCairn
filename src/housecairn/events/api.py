"""POST /api/v1/homes/<home_id>/events/: the only endpoint an `events` token can use."""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from housecairn.apitokens.models import ApiToken, Scope
from housecairn.events import services
from housecairn.events.models import Event
from housecairn.homes.scoping import HomeScopedMixin


class EventSerializer(serializers.ModelSerializer[Event]):
    payload = serializers.DictField(required=False, default=dict)

    class Meta:
        model = Event
        fields = ["id", "kind", "payload", "created_at"]
        read_only_fields = ["id", "created_at"]


class EventCreateView(HomeScopedMixin, generics.GenericAPIView[Event]):
    serializer_class = EventSerializer
    token_scope = Scope.EVENTS

    @extend_schema(responses={202: EventSerializer})
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        home = self.get_home()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = request.auth if isinstance(request.auth, ApiToken) else None
        try:
            event = services.record_event(
                request.user,  # type: ignore[arg-type]
                home,
                kind=serializer.validated_data["kind"],
                payload=serializer.validated_data["payload"],
                token=token,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"payload": exc.messages}) from exc
        return Response(self.get_serializer(event).data, status=status.HTTP_202_ACCEPTED)
