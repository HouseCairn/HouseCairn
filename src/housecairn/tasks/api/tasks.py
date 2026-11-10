"""API v1 of tasks (docs/adr/0004, 0031)."""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
)
from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from housecairn.accounts.models import User
from housecairn.accounts.names import person_name
from housecairn.core.pagination import DefaultCursorPagination
from housecairn.homes.models import Home
from housecairn.rooms.api import (
    HomeResourceMixin,
    _uuid_param,
    _validation,
)
from housecairn.rooms.models import Item, Room
from housecairn.tasks import durations, services
from housecairn.tasks.api.common import DATE_PARAMS, _date_param
from housecairn.tasks.api.materials import MaterialSummarySerializer
from housecairn.tasks.models import (
    OPEN_STATUSES,
    Contractor,
    Occurrence,
    Season,
    Task,
    TaskMaterial,
)


class TaskSerializer(serializers.ModelSerializer[Task]):
    room = serializers.PrimaryKeyRelatedField(
        queryset=Room.objects.none(), required=False, allow_null=True
    )
    item = serializers.PrimaryKeyRelatedField(
        queryset=Item.objects.none(), required=False, allow_null=True
    )
    assignee = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.none(),
        required=False,
        allow_null=True,
        help_text="A member of the home.",
    )
    assignee_name = serializers.SerializerMethodField(
        help_text="The name shown for the assignee (display name, never the address)."
    )
    estimated_minutes = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=durations.MIN_MINUTES,
        max_value=durations.MAX_MINUTES,
        help_text="Estimated duration in minutes, from 1 to 43200 (thirty days). The screens "
        "take a number and a unit and store minutes.",
    )
    estimated_text = serializers.SerializerMethodField(
        help_text="The estimated duration as people read it, in the language of the request "
        '("1 h 30", "2 days").'
    )
    contractor = serializers.PrimaryKeyRelatedField(
        queryset=Contractor.objects.none(), required=False, allow_null=True
    )
    season = serializers.ChoiceField(
        choices=[("", "all year"), *Season.choices],
        required=False,
        help_text="`spring`, `summer`, `autumn`, `winter` and `heating` follow the hemisphere "
        "of the home and set the two months below; `custom` takes the months given; empty is "
        "the whole year. Months given without a season make a custom one.",
    )
    due_on = serializers.DateField(
        source="open_due_on",
        required=False,
        allow_null=True,
        help_text="Due date of the open occurrence. Writing it moves that occurrence.",
    )
    materials = MaterialSummarySerializer(
        many=True,
        read_only=True,
        source="material_lines",
        help_text="The stock items the task needs; change them in `task-materials`.",
    )
    open_occurrence = serializers.UUIDField(
        source="open_occurrence_id",
        read_only=True,
        allow_null=True,
        help_text="The occurrence to do now; null when the task is done for good.",
    )

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "room",
            "item",
            "priority",
            "due_on",
            "open_occurrence",
            "materials",
            "estimated_minutes",
            "estimated_text",
            "labour_budget",
            "material_budget",
            "notes",
            "procedure",
            "assignee",
            "assignee_name",
            "contractor",
            "repeat_mode",
            "repeat_unit",
            "repeat_interval",
            "season",
            "season_start_month",
            "season_end_month",
            "hide_days_before",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        home: Home | None = self.context.get("home")
        if home is not None:
            self.fields["room"].queryset = Room.objects.filter(home=home)  # type: ignore[attr-defined]
            self.fields["item"].queryset = Item.objects.filter(home=home)  # type: ignore[attr-defined]
            self.fields["assignee"].queryset = services.members_for_forms(home)  # type: ignore[attr-defined]
            self.fields["contractor"].queryset = Contractor.objects.filter(home=home)  # type: ignore[attr-defined]

    def get_assignee_name(self, task: Task) -> str:
        return person_name(task.assignee)

    @extend_schema_field(OpenApiTypes.STR)
    def get_estimated_text(self, task: Task) -> str:
        return durations.label(task.estimated_minutes) if task.estimated_minutes else ""


class TaskViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[Task],
):
    """Tasks of a home. Only `title` is required.

    A task has one open occurrence at a time, which `due_on` shows and moves; closing
    it (`.../occurrences/<id>/complete/`) creates the next one when the task repeats.
    """

    serializer_class = TaskSerializer
    queryset = Task.objects.none()
    pagination_class = DefaultCursorPagination
    lookup_field = "id"
    lookup_url_kwarg = "task_id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> models.QuerySet[Task]:
        open_rows = Occurrence.objects.filter(task=models.OuterRef("pk"), status__in=OPEN_STATUSES)
        tasks = (
            services.tasks_of(self.get_home())
            .annotate(
                open_occurrence_id=models.Subquery(open_rows.values("id")[:1]),
                open_due_on=models.Subquery(open_rows.values("due_on")[:1]),
            )
            .prefetch_related(
                models.Prefetch(
                    "materials",
                    queryset=TaskMaterial.objects.filter(
                        article__deleted_at__isnull=True
                    ).select_related("article"),
                    to_attr="material_lines",
                )
            )
        )
        params = self.request.query_params
        for name, field in (
            ("room", "room_id"),
            ("item", "item_id"),
            ("assignee", "assignee_id"),
            ("contractor", "contractor_id"),
        ):
            value = _uuid_param(self.request, name)
            if value is not None:
                tasks = tasks.filter(**{field: value})
        match params.get("status"):
            case "open":
                tasks = tasks.filter(open_occurrence_id__isnull=False)
            case "closed":
                tasks = tasks.filter(open_occurrence_id__isnull=True)
            case None | "":
                pass
            case _:
                raise exceptions.ValidationError({"status": ["Use open or closed."]})
        match params.get("due"):
            case "none":
                # Active (not deleted, with an open occurrence) and nothing planned: an open
                # occurrence without a date. A closed task has no open occurrence at all.
                tasks = tasks.filter(open_occurrence_id__isnull=False, open_due_on__isnull=True)
            case None | "":
                pass
            case _:
                raise exceptions.ValidationError({"due": ["Use none."]})
        if (before := _date_param(self.request, "due_before")) is not None:
            tasks = tasks.filter(open_due_on__lte=before)
        if (after := _date_param(self.request, "due_after")) is not None:
            tasks = tasks.filter(open_due_on__gte=after)
        query = params.get("q", "").strip()
        return tasks.filter(title__icontains=query) if query else tasks

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Only titles containing this text."),
            OpenApiParameter("status", str, enum=["open", "closed"]),
            OpenApiParameter("room", OpenApiTypes.UUID),
            OpenApiParameter("item", OpenApiTypes.UUID),
            OpenApiParameter("assignee", OpenApiTypes.UUID),
            OpenApiParameter("contractor", OpenApiTypes.UUID),
            OpenApiParameter(
                "due",
                str,
                enum=["none"],
                description="`none`: only the active tasks with no due date, whose open "
                "occurrence has no date; closed tasks are left out.",
            ),
            *DATE_PARAMS,
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        due_on = data.pop("open_due_on", None)
        try:
            task = services.create_task(request.user, self.get_home(), due_on=due_on, **data)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(
            self.get_serializer(self.get_queryset().get(id=task.id)).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        task = self.get_object()
        serializer = self.get_serializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        extra = {"due_on": data.pop("open_due_on")} if "open_due_on" in data else {}
        try:
            services.update_task(request.user, task, **extra, **data)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(self.get_queryset().get(id=task.id)).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_task(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)
