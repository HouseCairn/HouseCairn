"""API v1 of the materials of a task: the stock items it needs (docs/adr/0004, 0046)."""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from housecairn.homes.models import Home
from housecairn.rooms.api import HomeResourceMixin, _uuid_param, _validation
from housecairn.stock.models import Article
from housecairn.tasks import materials, services
from housecairn.tasks.models import Task, TaskMaterial


class MaterialSummarySerializer(serializers.ModelSerializer[TaskMaterial]):
    """A line as the task shows it."""

    article_name = serializers.CharField(source="article.name", read_only=True)
    unit = serializers.CharField(source="article.unit_label", read_only=True)

    class Meta:
        model = TaskMaterial
        fields = ["id", "article", "article_name", "quantity", "unit"]
        read_only_fields = fields


class MaterialSerializer(serializers.ModelSerializer[TaskMaterial]):
    task = serializers.PrimaryKeyRelatedField(
        queryset=Task.objects.none(), help_text="The task; it cannot be changed once created."
    )
    article = serializers.PrimaryKeyRelatedField(
        queryset=Article.objects.none(),
        help_text="A stock item of the same home; it cannot be changed once created.",
    )
    article_name = serializers.CharField(source="article.name", read_only=True)
    unit = serializers.CharField(source="article.unit_label", read_only=True)
    stock_quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
        help_text="What is in stock now; marking the task done takes `quantity` from it.",
    )

    class Meta:
        model = TaskMaterial
        fields = [
            "id",
            "task",
            "article",
            "article_name",
            "quantity",
            "unit",
            "stock_quantity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {"quantity": {"min_value": Decimal("0.01")}}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        home: Home | None = self.context.get("home")
        if home is not None:
            self.fields["task"].queryset = services.tasks_of(home)  # type: ignore[attr-defined]
            self.fields["article"].queryset = Article.objects.filter(home=home)  # type: ignore[attr-defined]


class MaterialViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[TaskMaterial],
):
    """The stock items a task needs, with the quantity. Marking the task done takes them
    from the stock; undoing puts them back."""

    serializer_class = MaterialSerializer
    queryset = TaskMaterial.objects.none()
    lookup_field = "id"
    lookup_url_kwarg = "material_id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> models.QuerySet[TaskMaterial]:
        rows = materials.materials_of_home(self.get_home())
        for name, field in (("task", "task_id"), ("article", "article_id")):
            value = _uuid_param(self.request, name)
            if value is not None:
                rows = rows.filter(**{field: value})
        return rows

    @extend_schema(
        parameters=[
            OpenApiParameter("task", OpenApiTypes.UUID),
            OpenApiParameter("article", OpenApiTypes.UUID),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def _fresh(self, line: TaskMaterial) -> TaskMaterial:
        return materials.materials_of_home(self.get_home()).get(id=line.id)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            line = materials.add_material(
                request.user, data["task"], data["article"], data["quantity"]
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(self._fresh(line)).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        line = self.get_object()
        serializer = self.get_serializer(line, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        for field, current in (("task", line.task), ("article", line.article)):
            if data.get(field, current) != current:
                raise exceptions.ValidationError({field: [f"A line cannot change {field}."]})
        try:
            if "quantity" in data:
                materials.update_material(request.user, line, quantity=data["quantity"])
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(self._fresh(line)).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        materials.remove_material(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)
