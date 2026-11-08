"""API v1 of tasks, occurrences and contractors (docs/adr/0004, 0031-0033).

Validation only; rules live in `services`. Everything the screens do is done here.
"""

import datetime
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.db.models.functions import Coalesce
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from housecairn.accounts.models import User
from housecairn.core.pagination import DefaultCursorPagination
from housecairn.homes.models import Home
from housecairn.rooms.api import (
    HomeResourceMixin,
    _uuid_param,
    _validation,
)
from housecairn.rooms.models import Item, Room
from housecairn.tasks import services
from housecairn.tasks.models import (
    OPEN_STATUSES,
    Contractor,
    Occurrence,
    Status,
    Task,
)

_FAR = datetime.date(9999, 12, 31)


def _date_param(request: Request, name: str) -> datetime.date | None:
    raw = request.query_params.get(name)
    if raw is None:
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        raise exceptions.ValidationError({name: ["Not a valid date (YYYY-MM-DD)."]}) from None


DATE_PARAMS = [
    OpenApiParameter("due_before", OpenApiTypes.DATE, description="Due on or before this date."),
    OpenApiParameter("due_after", OpenApiTypes.DATE, description="Due on or after this date."),
]


# ---------- contractors ----------


class ContractorSerializer(serializers.ModelSerializer[Contractor]):
    class Meta:
        model = Contractor
        fields = ["id", "name", "trade", "note", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ContractorViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[Contractor],
):
    """People and companies who do work in a home: name, trade, a note."""

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


# ---------- tasks ----------


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
    contractor = serializers.PrimaryKeyRelatedField(
        queryset=Contractor.objects.none(), required=False, allow_null=True
    )
    due_on = serializers.DateField(
        source="open_due_on",
        required=False,
        allow_null=True,
        help_text="Due date of the open occurrence. Writing it moves that occurrence.",
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
            "estimated_minutes",
            "labour_budget",
            "material_budget",
            "notes",
            "procedure",
            "assignee",
            "contractor",
            "repeat_mode",
            "repeat_unit",
            "repeat_interval",
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
        tasks = services.tasks_of(self.get_home()).annotate(
            open_occurrence_id=models.Subquery(open_rows.values("id")[:1]),
            open_due_on=models.Subquery(open_rows.values("due_on")[:1]),
        )
        params = self.request.query_params
        for name, field in (("room", "room_id"), ("item", "item_id"), ("assignee", "assignee_id")):
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


# ---------- occurrences ----------


class OccurrencePagination(DefaultCursorPagination):
    """The oldest due date first, so that the arrears come first; no date last."""

    ordering = ("sort_due", "created_at", "id")  # type: ignore[assignment]


class OccurrenceSerializer(serializers.ModelSerializer[Occurrence]):
    task_title = serializers.CharField(source="task.title", read_only=True)
    room = serializers.UUIDField(source="task.room_id", read_only=True, allow_null=True)
    item = serializers.UUIDField(source="task.item_id", read_only=True, allow_null=True)
    completed_by = serializers.UUIDField(source="completed_by_id", read_only=True, allow_null=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Occurrence
        fields = [
            "id",
            "task",
            "task_title",
            "room",
            "item",
            "status",
            "due_on",
            "visible_from",
            "postponed_from",
            "completed_on",
            "completed_by",
            "actual_cost",
            "completion_note",
            "is_overdue",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "task",
            "status",
            "due_on",
            "visible_from",
            "postponed_from",
            "created_at",
            "updated_at",
        ]

    def get_is_overdue(self, occurrence: Occurrence) -> bool:
        return occurrence.is_overdue(services.today())


class CompleteSerializer(serializers.Serializer[Any]):
    completed_on = serializers.DateField(
        required=False, help_text="Defaults to today; cannot be in the future."
    )
    actual_cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, min_value=0
    )
    note = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")


class PostponeSerializer(serializers.Serializer[Any]):
    due_on = serializers.DateField(help_text="The new date; not in the past.")


class ClosingSerializer(serializers.Serializer[Any]):
    occurrence = OccurrenceSerializer()
    next = OccurrenceSerializer(allow_null=True, help_text="The occurrence created; null if none.")


class OccurrenceViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet[Occurrence],
):
    """Each time a task has to be done, with its status.

    `complete` (a single call, for every task) closes an occurrence as done and creates
    the next when the task repeats; `undo` takes it back, the created occurrence included.
    `PATCH` completes what is known of a task that is done: date, real cost, note.
    """

    serializer_class = OccurrenceSerializer
    queryset = Occurrence.objects.none()
    pagination_class = OccurrencePagination
    lookup_field = "id"
    lookup_url_kwarg = "occurrence_id"
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self) -> models.QuerySet[Occurrence]:
        rows = services.occurrences_of(self.get_home()).annotate(
            sort_due=Coalesce("due_on", models.Value(_FAR))
        )
        params = self.request.query_params
        for name, field in (
            ("task", "task_id"),
            ("room", "task__room_id"),
            ("item", "task__item_id"),
            ("assignee", "task__assignee_id"),
        ):
            value = _uuid_param(self.request, name)
            if value is not None:
                rows = rows.filter(**{field: value})
        match params.get("status"):
            case "open":
                rows = rows.filter(status__in=OPEN_STATUSES)
            case "closed":
                rows = rows.filter(status__in=[Status.DONE, Status.SKIPPED])
            case "planned" | "postponed" | "done" | "skipped" as one:
                rows = rows.filter(status=one)
            case None | "":
                pass
            case _:
                raise exceptions.ValidationError(
                    {"status": ["Use planned, postponed, done, skipped, open or closed."]}
                )
        if params.get("overdue") in ("1", "true"):
            rows = rows.filter(status__in=OPEN_STATUSES, due_on__lt=services.today())
        if (before := _date_param(self.request, "due_before")) is not None:
            rows = rows.filter(due_on__lte=before)
        if (after := _date_param(self.request, "due_after")) is not None:
            rows = rows.filter(due_on__gte=after)
        if params.get("include_hidden") not in ("1", "true"):
            rows = rows.filter(
                ~models.Q(status__in=OPEN_STATUSES)
                | models.Q(visible_from__isnull=True)
                | models.Q(visible_from__lte=services.today())
            )
        return rows

    @extend_schema(
        parameters=[
            OpenApiParameter("task", OpenApiTypes.UUID),
            OpenApiParameter("room", OpenApiTypes.UUID),
            OpenApiParameter("item", OpenApiTypes.UUID),
            OpenApiParameter("assignee", OpenApiTypes.UUID),
            OpenApiParameter(
                "status",
                str,
                enum=["planned", "postponed", "done", "skipped", "open", "closed"],
            ),
            OpenApiParameter("overdue", bool, description="Open and past their date."),
            OpenApiParameter(
                "include_hidden",
                bool,
                description="Also the open occurrences hidden until a few days before their date.",
            ),
            *DATE_PARAMS,
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        occurrence = self.get_object()
        serializer = self.get_serializer(occurrence, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            services.update_occurrence(request.user, occurrence, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(occurrence).data)

    def _closing(self, request: Request, closing: services.Closing) -> Response:
        context = self.get_serializer_context()
        return Response(
            {
                "occurrence": OccurrenceSerializer(closing.occurrence, context=context).data,
                "next": OccurrenceSerializer(closing.next, context=context).data
                if closing.next
                else None,
            }
        )

    @extend_schema(request=CompleteSerializer, responses=ClosingSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Mark done and create the next occurrence, in one call. `undo` takes it back."""
        occurrence = self.get_object()
        serializer = CompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            closing = services.complete(
                request.user,
                occurrence,
                on=data.get("completed_on"),
                actual_cost=data.get("actual_cost"),
                note=data["note"],
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return self._closing(request, closing)

    @extend_schema(request=None, responses=ClosingSerializer)
    @action(detail=True, methods=["post"])
    def skip(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Ignore this time: closed without being done; the next occurrence is created."""
        try:
            closing = services.skip(request.user, self.get_object())
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return self._closing(request, closing)

    @extend_schema(request=PostponeSerializer, responses=OccurrenceSerializer)
    @action(detail=True, methods=["post"])
    def postpone(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Move the open occurrence to another day (status `postponed`)."""
        occurrence = self.get_object()
        serializer = PostponeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            moved = services.postpone(request.user, occurrence, serializer.validated_data["due_on"])
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(moved).data)

    @extend_schema(request=None, responses=OccurrenceSerializer)
    @action(detail=True, methods=["post"])
    def undo(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Take back a `complete` or a `skip`: the occurrence is open again, the next one is gone.

        Refused (400) once the next occurrence has been changed.
        """
        try:
            reopened = services.undo(request.user, self.get_object())
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(reopened).data)
