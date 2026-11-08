"""API v1 of tasks, occurrences, contractors and attachments (docs/adr/0004, 0031-0034).

Validation only; rules live in `services`. Everything the screens do is done here.
"""

import datetime
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.db.models.functions import Coalesce, TruncDate
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
)
from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from housecairn.accounts.models import User
from housecairn.core.pagination import DefaultCursorPagination
from housecairn.homes.models import Home
from housecairn.homes.scoping import open_homes_for_request
from housecairn.rooms import conf
from housecairn.rooms.api import (
    BinaryRenderer,
    HomeResourceMixin,
    PayloadTooLarge,
    _uuid_param,
    _validation,
)
from housecairn.rooms.models import Item, Room
from housecairn.tasks import agenda, files, services
from housecairn.tasks.models import (
    CLOSED_STATUSES,
    OPEN_STATUSES,
    Attachment,
    Contractor,
    DisplayPreference,
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


# ---------- Today, My home, display preferences ----------


class PreferencesSerializer(serializers.ModelSerializer[DisplayPreference]):
    language = serializers.ChoiceField(
        choices=[("", "automatic"), *settings.LANGUAGES],
        required=False,
        help_text="Interface language of the person: a language the instance ships, or empty "
        "to follow the browser, then the default of the instance.",
    )

    class Meta:
        model = DisplayPreference
        fields = [
            "today_group",
            "horizon_days",
            "show_overdue",
            "show_upcoming",
            "show_season",
            "language",
        ]

    def to_representation(self, instance: DisplayPreference) -> dict[str, Any]:
        data: dict[str, Any] = super().to_representation(instance)
        # A value written behind the model's back is not a choice the instance ships.
        if data["language"] not in {code for code, _name in settings.LANGUAGES}:
            data["language"] = ""
        return data


class SectionSerializer(serializers.Serializer[Any]):
    key = serializers.CharField(
        help_text="`overdue`, `today`, `upcoming`, `room`, `person`, `day` or `season`."
    )
    title = serializers.CharField(help_text="Heading, in the language of the request.")
    ref = serializers.CharField(
        allow_null=True, help_text="The room or the person of a `room` or `person` section."
    )
    day = serializers.DateField(allow_null=True, help_text="The date of a `day` section.")
    occurrences = OccurrenceSerializer(many=True, source="rows")


class TodaySerializer(serializers.Serializer[Any]):
    preferences = PreferencesSerializer()
    sections = SectionSerializer(many=True)


class TodayView(HomeResourceMixin, APIView):
    """What to do in a home, laid out by the display preferences of the caller."""

    @extend_schema(responses=TodaySerializer)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        home = self.get_home()
        prefs = agenda.preferences_of(request.user)  # type: ignore[arg-type]
        context = {"request": request, "home": home}
        sections = agenda.today_sections(home, prefs)
        return Response(
            TodaySerializer({"preferences": prefs, "sections": sections}, context=context).data
        )


class WarrantySerializer(serializers.ModelSerializer[Item]):
    room = serializers.UUIDField(source="room_id", read_only=True)

    class Meta:
        model = Item
        fields = ["id", "name", "room", "warranty_ends_on"]


class DigestSerializer(serializers.Serializer[Any]):
    home = serializers.UUIDField(source="home.id")
    name = serializers.CharField(source="home.name")
    mine = OccurrenceSerializer(many=True, help_text="Open tasks assigned to the caller.")
    overdue = OccurrenceSerializer(many=True, help_text="Late for others or for nobody.")
    unassigned = OccurrenceSerializer(many=True, help_text="Open, not late, nobody in charge.")
    warranties = WarrantySerializer(many=True, help_text="Warranties ending in 60 days.")


class MyHomeView(APIView):
    """What concerns the caller, in one home or in all of theirs."""

    @extend_schema(
        parameters=[OpenApiParameter("home", OpenApiTypes.UUID, description="Only this home.")],
        responses=DigestSerializer(many=True),
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        homes = list(open_homes_for_request(request).order_by("name"))
        wanted = _uuid_param(request, "home")
        if wanted is not None:
            homes = [h for h in homes if h.id == wanted]
            if not homes:
                raise exceptions.NotFound
        digests = agenda.my_home(request.user, homes)  # type: ignore[arg-type]
        return Response(DigestSerializer(digests, many=True, context={"request": request}).data)


class PreferencesView(APIView):
    """The display preferences of the caller, which only they can read or change."""

    @extend_schema(responses=PreferencesSerializer)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(PreferencesSerializer(agenda.preferences_of(request.user)).data)  # type: ignore[arg-type]

    @extend_schema(request=PreferencesSerializer, responses=PreferencesSerializer)
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = PreferencesSerializer(
            agenda.preferences_of(request.user),  # type: ignore[arg-type]
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        try:
            prefs = agenda.update_preferences(request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(PreferencesSerializer(prefs).data)


# ---------- attachments ----------


class AttachmentSerializer(serializers.ModelSerializer[Attachment]):
    task: serializers.PrimaryKeyRelatedField[Task] = serializers.PrimaryKeyRelatedField(
        read_only=True
    )
    occurrence: serializers.PrimaryKeyRelatedField[Occurrence] = serializers.PrimaryKeyRelatedField(
        read_only=True, allow_null=True
    )
    content_url = serializers.SerializerMethodField(help_text="Address of the file.")
    thumbnail_url = serializers.SerializerMethodField(
        help_text="Address of the thumbnail; null for a file that is not an image."
    )

    class Meta:
        model = Attachment
        fields = [
            "id",
            "task",
            "occurrence",
            "name",
            "content_type",
            "is_image",
            "size_bytes",
            "width",
            "height",
            "content_url",
            "thumbnail_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "content_type",
            "is_image",
            "size_bytes",
            "width",
            "height",
            "created_at",
            "updated_at",
        ]

    def _url(self, name: str, attachment: Attachment) -> str:
        return str(
            reverse(
                name,
                kwargs={"home_id": attachment.home_id, "attachment_id": attachment.id},
                request=self.context["request"],
            )
        )

    @extend_schema_field(OpenApiTypes.URI)
    def get_content_url(self, attachment: Attachment) -> str:
        return self._url("api-v1:home-attachment-content", attachment)

    @extend_schema_field(OpenApiTypes.URI)
    def get_thumbnail_url(self, attachment: Attachment) -> str | None:
        if not attachment.is_image:
            return None
        return self._url("api-v1:home-attachment-thumbnail", attachment)


class AttachmentUploadSerializer(serializers.Serializer[Any]):
    file = serializers.FileField(
        help_text="A JPEG, PNG or WebP image, or a PDF, text, Word, Excel or OpenDocument file."
    )
    task = serializers.UUIDField()
    occurrence = serializers.UUIDField(required=False, help_text="One of the task's occurrences.")
    name = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


class AttachmentViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[Attachment],
):
    """Photos and files of tasks. Upload as `multipart/form-data`.

    An image is checked by its content and written again without its metadata
    (location included); any other file must be of an accepted type, checked by its
    content. All are limited in size and only ever served back as stored.
    """

    serializer_class = AttachmentSerializer
    queryset = Attachment.objects.none()
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    lookup_field = "id"
    lookup_url_kwarg = "attachment_id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> models.QuerySet[Attachment]:
        rows = services.attachments_of(self.get_home())
        task = _uuid_param(self.request, "task")
        occurrence = _uuid_param(self.request, "occurrence")
        if task is not None:
            rows = rows.filter(task_id=task)
        if occurrence is not None:
            rows = rows.filter(occurrence_id=occurrence)
        return rows

    @extend_schema(
        parameters=[
            OpenApiParameter("task", OpenApiTypes.UUID),
            OpenApiParameter("occurrence", OpenApiTypes.UUID),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request={"multipart/form-data": AttachmentUploadSerializer},
        responses={201: AttachmentSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        home = self.get_home()
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
        if declared > conf.photo_max_bytes() + conf.MULTIPART_OVERHEAD:
            raise PayloadTooLarge
        serializer = AttachmentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        task: Task = get_object_or_404(services.tasks_of(home), id=data["task"])
        occurrence: Occurrence | None = None
        if "occurrence" in data:
            occurrence = get_object_or_404(services.occurrences_of(home), id=data["occurrence"])
        try:
            attachment = services.add_attachment(
                request.user, task, upload=data["file"], occurrence=occurrence, name=data["name"]
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(attachment).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        attachment = self.get_object()
        serializer = self.get_serializer(attachment, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            attachment = services.update_attachment(
                request.user,
                attachment,
                name=serializer.validated_data.get("name", attachment.name),
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(attachment).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_attachment(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={(200, "*/*"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"], renderer_classes=[BinaryRenderer])
    def content(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """The file as stored: an image inline, any other file as a download, never sniffed."""
        return files.attachment_response(self.get_object())

    @extend_schema(responses={(200, "image/jpeg"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"], renderer_classes=[BinaryRenderer])
    def thumbnail(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """A JPEG thumbnail of an image (404 for a file that is not an image)."""
        return files.attachment_response(self.get_object(), thumbnail=True)
