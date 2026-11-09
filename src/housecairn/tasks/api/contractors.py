"""API v1 of contractors (docs/adr/0004, 0045)."""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.http.response import HttpResponseBase
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_field,
)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from housecairn.rooms.api import (
    BinaryRenderer,
    HomeResourceMixin,
    _validation,
)
from housecairn.tasks import services, vcard
from housecairn.tasks.models import (
    Contractor,
    Trade,
)


class ContractorSerializer(serializers.ModelSerializer[Contractor]):
    trade = serializers.ChoiceField(
        choices=[("", "none"), *Trade.choices],
        required=False,
        help_text="A trade of the list, or `other` with `trade_other` saying which.",
    )
    trade_label = serializers.SerializerMethodField(
        help_text="The trade as people read it, in the language of the request."
    )

    class Meta:
        model = Contractor
        fields = [
            "id",
            "name",
            "trade",
            "trade_other",
            "trade_label",
            "phone",
            "email",
            "address",
            "note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_trade_label(self, contractor: Contractor) -> str:
        return contractor.trade_label


class ContractorViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[Contractor],
):
    """People and companies who do work in a home: name, trade, how to reach them, a note.

    Their tasks are the tasks of the home filtered by `contractor`.
    """

    serializer_class = ContractorSerializer
    queryset = Contractor.objects.none()
    lookup_field = "id"
    lookup_url_kwarg = "contractor_id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> models.QuerySet[Contractor]:
        return services.contractors_of(self.get_home())

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            contractor = services.create_contractor(
                request.user, self.get_home(), **serializer.validated_data
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(contractor).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        contractor = self.get_object()
        serializer = self.get_serializer(contractor, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            services.update_contractor(request.user, contractor, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(contractor).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_contractor(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={(200, "text/vcard"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"], renderer_classes=[BinaryRenderer])
    def vcard(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """The contact file of the contractor (vCard 3.0), readable by every member."""
        return vcard.response(self.get_object())
