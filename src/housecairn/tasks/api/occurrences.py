"""API v1 of occurrences (docs/adr/0004, 0031, 0033)."""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.db.models.functions import Coalesce, TruncDate
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
)
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from housecairn.accounts.names import person_name
from housecairn.core.pagination import DefaultCursorPagination
from housecairn.rooms.api import (
    HomeResourceMixin,
    _uuid_param,
    _validation,
)
from housecairn.tasks import agenda, services
from housecairn.tasks.api.common import _FAR, DATE_PARAMS, _date_param
from housecairn.tasks.models import (
    CLOSED_STATUSES,
    OPEN_STATUSES,
    Occurrence,
    Status,
)


class OccurrencePagination(DefaultCursorPagination):
    """The oldest due date first, so that the arrears come first; no date last."""

    ordering = ("sort_due", "created_at", "id")  # type: ignore[assignment]

    def get_ordering(self, request: Request, queryset: Any, view: Any) -> tuple[str, ...]:
        """`?ordering=recent` is the History order: the latest closed first."""
        if request.query_params.get("ordering") == "recent":
            return ("-closed_on", "-created_at", "-id")
        return tuple(super().get_ordering(request, queryset, view))


class OccurrenceSerializer(serializers.ModelSerializer[Occurrence]):
    task_title = serializers.CharField(source="task.title", read_only=True)
    room = serializers.UUIDField(source="task.room_id", read_only=True, allow_null=True)
    item = serializers.UUIDField(source="task.item_id", read_only=True, allow_null=True)
    completed_by = serializers.UUIDField(source="completed_by_id", read_only=True, allow_null=True)
    completed_by_name = serializers.SerializerMethodField(
        help_text="The name shown for who closed it (display name, never the address)."
    )
    assignee_name = serializers.SerializerMethodField(
        help_text="The name shown for the assignee of the task."
    )
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
            "completed_by_name",
            "assignee_name",
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

    def get_completed_by_name(self, occurrence: Occurrence) -> str:
        return person_name(occurrence.completed_by)

    def get_assignee_name(self, occurrence: Occurrence) -> str:
        return person_name(occurrence.task.assignee)

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


class CostSerializer(serializers.Serializer[Any]):
    total = serializers.DecimalField(max_digits=14, decimal_places=2)
    with_cost = serializers.IntegerField(help_text="Occurrences where a real cost was entered.")
    count = serializers.IntegerField(help_text="Occurrences selected.")


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
            sort_due=Coalesce("due_on", models.Value(_FAR)),
            closed_on=Coalesce("completed_on", TruncDate("updated_at")),
        )
        params = self.request.query_params
        for name, field in (
            ("task", "task_id"),
            ("room", "task__room_id"),
            ("item", "task__item_id"),
            ("assignee", "task__assignee_id"),
            ("contractor", "task__contractor_id"),
            ("completed_by", "completed_by_id"),
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
        if (found := params.get("q", "").strip()[:200]) != "":
            rows = rows.filter(
                models.Q(task__title__icontains=found) | models.Q(completion_note__icontains=found)
            )
        if (closed_after := _date_param(self.request, "closed_after")) is not None:
            rows = rows.filter(closed_on__gte=closed_after, status__in=CLOSED_STATUSES)
        if (closed_before := _date_param(self.request, "closed_before")) is not None:
            rows = rows.filter(closed_on__lte=closed_before, status__in=CLOSED_STATUSES)
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
            OpenApiParameter("contractor", OpenApiTypes.UUID),
            OpenApiParameter(
                "completed_by", OpenApiTypes.UUID, description="Who closed the occurrence."
            ),
            OpenApiParameter(
                "q", str, description="Words of the task title or of the note of the occurrence."
            ),
            OpenApiParameter(
                "closed_after", OpenApiTypes.DATE, description="Closed on or after this date."
            ),
            OpenApiParameter(
                "closed_before", OpenApiTypes.DATE, description="Closed on or before this date."
            ),
            OpenApiParameter(
                "ordering",
                str,
                enum=["recent"],
                description="`recent`: the latest closed first, as the History screen.",
            ),
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

    @extend_schema(
        parameters=[OpenApiParameter("status", str, enum=["done", "skipped", "closed"])],
        responses=CostSerializer,
        description=(
            "The real cost entered on the occurrences that the same filters as the list "
            "select: the History total. Add `status=closed` for what is done or skipped."
        ),
    )
    @action(detail=False, methods=["get"])
    def cost(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        total = agenda.cost_of(self.get_queryset())
        return Response(CostSerializer(total).data)

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
