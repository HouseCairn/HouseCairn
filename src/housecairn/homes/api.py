"""API v1 of homes. Validation only; rules live in `services`."""

from typing import Any

from django.db import models
from drf_spectacular.utils import extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from housecairn.homes import services
from housecairn.homes.models import Home, Role
from housecairn.homes.scoping import HomeScopedMixin


class HomeSerializer(serializers.ModelSerializer[Home]):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Home
        fields = ["id", "name", "currency", "role", "created_at", "updated_at"]
        read_only_fields = ["id", "role", "created_at", "updated_at"]

    @extend_schema_field(serializers.ChoiceField(choices=Role.choices, allow_null=True))
    def get_role(self, home: Home) -> str | None:
        role = services.role_of(self.context["request"].user, home)
        return role.value if role else None


class HomeViewSet(
    HomeScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[Home],
):
    """Homes of the authenticated user (narrowed to the token's homes, if any)."""

    serializer_class = HomeSerializer
    lookup_field = "id"
    lookup_url_kwarg = "home_id"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self) -> models.QuerySet[Home]:
        return self.get_homes()

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        home = self.get_object()
        serializer = self.get_serializer(home, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        home = services.update_home(request.user, home, **serializer.validated_data)
        return Response(self.get_serializer(home).data)
