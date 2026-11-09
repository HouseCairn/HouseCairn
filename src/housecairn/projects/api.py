"""API v1 of projects, budget lines, quotes, files, tasks and the envelope (docs/adr/0050).

Validation only; rules live in `services`. Amounts are decimal strings in the currency of
the home (`"1250.50"`), never numbers a client could round.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.http.response import HttpResponseBase
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
    inline_serializer,
)
from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from housecairn.core.pagination import DefaultCursorPagination
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.projects import links, services
from housecairn.projects.files import file_response
from housecairn.projects.models import (
    BudgetLine,
    Project,
    ProjectFile,
    ProjectLink,
    ProjectStatus,
    ProjectTask,
    Quote,
)
from housecairn.rooms import conf
from housecairn.rooms.api import (
    BinaryRenderer,
    HomeResourceMixin,
    PayloadTooLarge,
    _uuid_param,
    _validation,
)
from housecairn.rooms.models import Room
from housecairn.tasks import services as task_services
from housecairn.tasks.models import Contractor, Task


class MoneyString(serializers.DecimalField):
    """An amount sent as a string (`"1250.50"`), never as a JSON number a client could round."""

    default_error_messages = {
        "not_a_string": 'Send the amount as a string such as "1250.50", not as a number.'
    }

    def to_internal_value(self, data: Any) -> Decimal:
        if not isinstance(data, str):
            self.fail("not_a_string")
        return super().to_internal_value(data)


class MoneyModelSerializer(serializers.ModelSerializer[Any]):
    """Amounts of the model are `MoneyString`, whatever the field is called."""

    serializer_field_mapping = {
        **serializers.ModelSerializer.serializer_field_mapping,
        models.DecimalField: MoneyString,
    }


MONEY: dict[str, Any] = {"max_digits": 12, "decimal_places": 2, "min_value": Decimal("0")}
# An amount is a string with two decimals, so that no client rounds it.
MONEY_SCHEMA = {"type": "string", "format": "decimal", "example": "1250.50"}
PROJECT_PARAM = OpenApiParameter(
    "project", OpenApiTypes.UUID, description="Only the rows of this project."
)


def _check_size(request: Request) -> None:
    """Refuse an oversized body before reading any of it."""
    declared = int(request.META.get("CONTENT_LENGTH") or 0)
    if declared > conf.photo_max_bytes() + conf.MULTIPART_OVERHEAD:
        raise PayloadTooLarge


def _home(serializer: serializers.BaseSerializer[Any]) -> Home | None:
    home: Home | None = serializer.context.get("home")
    return home


def _amount_field(help_text: str) -> serializers.SerializerMethodField:
    return serializers.SerializerMethodField(help_text=help_text)


class AmountsMixin:
    """The planned, committed, paid and gap amounts of a row, as decimal strings.

    The three amounts of a project or a line are worked out with `Decimal` by `services`,
    once for a whole page (the view gives them in the context), never by the database.
    """

    context: dict[str, Any]

    def amounts_for(self, row: Any) -> "services.Amounts":
        raise NotImplementedError  # pragma: no cover

    @extend_schema_field(MONEY_SCHEMA)
    def get_planned(self, row: Any) -> str:
        return f"{self.amounts_for(row).planned:.2f}"

    @extend_schema_field(MONEY_SCHEMA)
    def get_committed(self, row: Any) -> str:
        return f"{self.amounts_for(row).committed:.2f}"

    @extend_schema_field(MONEY_SCHEMA)
    def get_paid(self, row: Any) -> str:
        return f"{self.amounts_for(row).paid:.2f}"

    @extend_schema_field(MONEY_SCHEMA)
    def get_gap(self, row: Any) -> str:
        return f"{self.amounts_for(row).gap:.2f}"

    @extend_schema_field({"type": "string", "enum": ["over", "under", "on"]})
    def get_budget_state(self, row: Any) -> str:
        return self.amounts_for(row).state


# ---------- projects ----------


class ProjectPagination(DefaultCursorPagination):
    """Projects in the order they were created; the list of the screens orders by status."""

    ordering = ("created_at", "id")


class ProjectSerializer(AmountsMixin, serializers.ModelSerializer[Project]):
    rooms: serializers.PrimaryKeyRelatedField[Room] = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Room.objects.none()
    )
    budget = MoneyString(
        write_only=True,
        required=False,
        help_text="On creation only: becomes the first budget line, planned.",
        **MONEY,
    )
    planned = _amount_field("The sum of the planned amounts of the budget lines.")
    committed = _amount_field("The sum of the quotes accepted on the budget lines.")
    paid = _amount_field("The sum of the paid amounts of the budget lines.")
    gap = _amount_field(
        "The sum of the gaps of the lines (each: planned less the more of committed and paid); "
        "negative: over budget."
    )
    budget_state = serializers.SerializerMethodField(
        help_text="`over`, `under` or `on` budget, from the gap."
    )
    season_months = serializers.SerializerMethodField(
        help_text="First and last month of the preferred season in the hemisphere of the home."
    )

    class Meta:
        model = Project
        fields = [
            "id",
            "title",
            "goal",
            "status",
            "priority",
            "rooms",
            "estimated_minutes",
            "season",
            "season_start_month",
            "season_end_month",
            "season_months",
            "budget",
            "planned",
            "committed",
            "paid",
            "gap",
            "budget_state",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        home = _home(self)
        if home is not None:
            self.fields["rooms"].child_relation.queryset = Room.objects.filter(home=home)  # type: ignore[attr-defined]

    def amounts_for(self, row: Project) -> services.Amounts:
        found: services.Amounts | None = self.context.get("amounts", {}).get(row.id)
        return found or services.amounts_of(row)

    @extend_schema_field({"type": "array", "items": {"type": "integer"}, "nullable": True})
    def get_season_months(self, project: Project) -> list[int] | None:
        months = project.season_months
        return list(months) if months else None


class ProjectViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[Project],
):
    """Projects of a home, with the total of their budget lines.

    `status` is one of idea, planned, in_progress, done, abandoned. The three amounts of a
    project are the sums of its lines: planned and paid are typed, committed comes from the
    accepted quotes.
    """

    serializer_class = ProjectSerializer
    queryset = Project.objects.none()
    pagination_class = ProjectPagination
    lookup_field = "id"
    lookup_url_kwarg = "project_id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> models.QuerySet[Project]:
        params = self.request.query_params
        room = _uuid_param(self.request, "room")
        projects = services.projects_of(self.get_home()).filter(
            **({"status": params["status"]} if params.get("status") else {}),
            **({"priority": params["priority"]} if params.get("priority") else {}),
            **({"season": params["season"]} if params.get("season") else {}),
            **({"rooms": room} if room is not None else {}),
        )
        if self.action == "list":
            # The rooms of a whole page in one query, not one per project.
            projects = projects.prefetch_related("rooms")
        return projects

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["amounts"] = getattr(self, "_amounts", {})
        return context

    def paginate_queryset(self, queryset: models.QuerySet[Any]) -> list[Any] | None:
        page = super().paginate_queryset(queryset)
        if page is not None:
            self._amounts = services.amounts_by_project(page)
        return page

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=ProjectStatus.values),
            OpenApiParameter("priority", str),
            OpenApiParameter("season", str),
            OpenApiParameter("room", OpenApiTypes.UUID),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        try:
            project = services.create_project(
                request.user,
                self.get_home(),
                rooms=data.pop("rooms", []),
                budget=data.pop("budget", None),
                **data,
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(project).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        project = self.get_object()
        serializer = self.get_serializer(project, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "budget" in data:
            raise exceptions.ValidationError(
                {"budget": ["Set at creation; change the budget lines afterwards."]}
            )
        try:
            project = services.update_project(
                request.user, project, rooms=data.pop("rooms", None), **data
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(project).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_project(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- budget lines ----------


class BudgetLineSerializer(AmountsMixin, MoneyModelSerializer):
    project = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.none(),
        help_text="The project; it cannot be changed once the line exists.",
    )
    committed = _amount_field("The sum of the quotes accepted on this line.")
    gap = _amount_field("Planned less the more of committed and paid; negative: over budget.")
    budget_state = serializers.SerializerMethodField(
        help_text="`over`, `under` or `on` budget, from the gap."
    )

    class Meta:
        model = BudgetLine
        fields = [
            "id",
            "project",
            "label",
            "nature",
            "planned",
            "committed",
            "paid",
            "gap",
            "budget_state",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        home = _home(self)
        if home is not None:
            self.fields["project"].queryset = Project.objects.filter(home=home)  # type: ignore[attr-defined]

    def amounts_for(self, row: BudgetLine) -> services.Amounts:
        committed = self.context.get("committed", {}).get(row.id)
        if committed is None:
            committed = services.committed_by_line([row])[row.id]
        return services.Amounts(row.planned, committed, row.paid)


class BudgetLineViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[BudgetLine],
):
    """The budget lines of the projects of a home: label, nature, planned, committed, paid."""

    serializer_class = BudgetLineSerializer
    queryset = BudgetLine.objects.none()
    pagination_class = ProjectPagination
    lookup_field = "id"
    lookup_url_kwarg = "line_id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> models.QuerySet[BudgetLine]:
        lines = services.lines_of(self.get_home())
        project = _uuid_param(self.request, "project")
        return lines.filter(project_id=project) if project is not None else lines

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["committed"] = getattr(self, "_committed", {})
        return context

    def paginate_queryset(self, queryset: models.QuerySet[Any]) -> list[Any] | None:
        page = super().paginate_queryset(queryset)
        if page is not None:
            self._committed = services.committed_by_line(page)
        return page

    @extend_schema(parameters=[PROJECT_PARAM])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        project = data.pop("project")
        try:
            line = services.create_line(request.user, project, **data)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(line).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        line = self.get_object()
        serializer = self.get_serializer(line, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if data.pop("project", line.project) != line.project:
            raise exceptions.ValidationError({"project": ["A line cannot change project."]})
        try:
            line = services.update_line(request.user, line, **data)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(line).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_line(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- quotes ----------


class QuoteSerializer(serializers.ModelSerializer[Quote]):
    project = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.none(),
        help_text="The project; it cannot be changed once the quote exists.",
    )
    contractor = serializers.PrimaryKeyRelatedField(
        queryset=Contractor.objects.none(),
        required=False,
        allow_null=True,
    )
    contractor_name = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=120,
        help_text=(
            "Instead of `contractor`: the name of a contractor of the home, created when it "
            "is new. Empty: nobody."
        ),
    )
    amount = MoneyString(required=False, **MONEY)
    budget_line: serializers.PrimaryKeyRelatedField[BudgetLine] = (
        serializers.PrimaryKeyRelatedField(
            queryset=BudgetLine.objects.none(),
            required=False,
            allow_null=True,
            help_text=(
                "The line an accepted quote is committed on; required with the status "
                "`accepted`, and empty with any other (`POST .../accept/` sets both)."
            ),
        )
    )

    class Meta:
        model = Quote
        fields = [
            "id",
            "project",
            "contractor",
            "contractor_name",
            "amount",
            "issued_on",
            "valid_until",
            "status",
            "budget_line",
            "note",
            "paperless_id",
            "paperless_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        home = _home(self)
        if home is not None:
            self.fields["project"].queryset = Project.objects.filter(home=home)  # type: ignore[attr-defined]
            self.fields["budget_line"].queryset = BudgetLine.objects.filter(home=home)  # type: ignore[attr-defined]
            contractor = self.fields["contractor"]
            assert isinstance(contractor, serializers.PrimaryKeyRelatedField)  # noqa: S101
            contractor.queryset = task_services.contractors_of(home)


class QuoteViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[Quote],
):
    """Quotes of the projects of a home. Accepting one commits its amount on a budget line."""

    serializer_class = QuoteSerializer
    queryset = Quote.objects.none()
    pagination_class = ProjectPagination
    lookup_field = "id"
    lookup_url_kwarg = "quote_id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> models.QuerySet[Quote]:
        quotes = services.quotes_of(self.get_home())
        project = _uuid_param(self.request, "project")
        return quotes.filter(project_id=project) if project is not None else quotes

    @extend_schema(parameters=[PROJECT_PARAM])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def _contractor(self, data: dict[str, Any]) -> dict[str, Any]:
        """`contractor_name` finds or creates the contractor; it replaces `contractor`."""
        if "contractor_name" in data:
            name = data.pop("contractor_name")
            if "contractor" in data:
                raise exceptions.ValidationError(
                    {"contractor_name": ["Give the contractor or its name, not both."]}
                )
            data["contractor"] = services.contractor_named(self.request.user, self.get_home(), name)
        return data

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        project = data.pop("project")
        try:
            with transaction.atomic():
                quote = services.create_quote(request.user, project, **self._contractor(data))
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(quote).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        quote = self.get_object()
        serializer = self.get_serializer(quote, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if data.pop("project", quote.project) != quote.project:
            raise exceptions.ValidationError({"project": ["A quote cannot change project."]})
        try:
            with transaction.atomic():
                quote = services.update_quote(request.user, quote, **self._contractor(data))
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(quote).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_quote(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=inline_serializer(
            "QuoteAcceptRequest",
            {"budget_line": serializers.UUIDField(help_text="The line to commit the amount on.")},
        ),
        responses=QuoteSerializer,
    )
    @action(detail=True, methods=["post"], url_path="accept", url_name="accept")
    def accept(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Accept the quote: its amount is committed on the chosen budget line of its project."""
        quote = self.get_object()
        # The role first, as in every other view: a reader gets a 403 whatever the body says.
        if not home_services.can_write(request.user, quote.home):
            raise PermissionDenied
        line_id = request.data.get("budget_line")
        wanted = _as_uuid(line_id)
        line = services.lines_of(self.get_home()).filter(pk=wanted).first() if wanted else None
        if line is None:
            raise exceptions.ValidationError({"budget_line": ["Choose a line of this home."]})
        try:
            quote = services.accept_quote(request.user, quote, line)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(quote).data)


def _as_uuid(raw: Any) -> UUID | None:
    try:
        return UUID(str(raw))
    except ValueError:
        return None


# ---------- photos and files ----------


class ProjectFileSerializer(serializers.ModelSerializer[ProjectFile]):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.none())
    quote = serializers.PrimaryKeyRelatedField(
        queryset=Quote.objects.none(),
        required=False,
        allow_null=True,
        help_text="Empty: a photo of the project. Set: a file of this quote (any allowed type).",
    )
    file = serializers.FileField(
        write_only=True, help_text="A JPEG, PNG or WebP image; a quote also takes a document."
    )
    content_url = serializers.SerializerMethodField(help_text="Address of the stored file.")
    thumbnail_url = serializers.SerializerMethodField(
        help_text="Address of the thumbnail of an image, or null."
    )

    class Meta:
        model = ProjectFile
        fields = [
            "id",
            "project",
            "quote",
            "name",
            "file",
            "content_type",
            "is_image",
            "size_bytes",
            "width",
            "height",
            "content_url",
            "thumbnail_url",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "content_type",
            "is_image",
            "size_bytes",
            "width",
            "height",
            "created_at",
        ]
        extra_kwargs = {"name": {"required": False, "allow_blank": True}}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        home = _home(self)
        if home is not None:
            self.fields["project"].queryset = Project.objects.filter(home=home)  # type: ignore[attr-defined]
            self.fields["quote"].queryset = Quote.objects.filter(home=home)  # type: ignore[attr-defined]

    @extend_schema_field(OpenApiTypes.URI)
    def get_content_url(self, stored: ProjectFile) -> str:
        return str(
            reverse(
                "api-v1:home-project-file-content",
                kwargs={"home_id": stored.home_id, "file_id": stored.id},
                request=self.context["request"],
            )
        )

    @extend_schema_field(OpenApiTypes.URI)
    def get_thumbnail_url(self, stored: ProjectFile) -> str | None:
        if not stored.thumbnail:
            return None
        return str(
            reverse(
                "api-v1:home-project-file-thumbnail",
                kwargs={"home_id": stored.home_id, "file_id": stored.id},
                request=self.context["request"],
            )
        )


class ProjectFileViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[ProjectFile],
):
    """Photos of the projects of a home, and the files of their quotes.

    Sent as `multipart/form-data` (`file`), checked by their content, written again
    without their metadata (location included) and limited in size and by the quotas of
    the home. A file is deleted, not changed.
    """

    serializer_class = ProjectFileSerializer
    queryset = ProjectFile.objects.none()
    pagination_class = ProjectPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    lookup_field = "id"
    lookup_url_kwarg = "file_id"
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self) -> models.QuerySet[ProjectFile]:
        # The picture of a link is read through here but belongs to its link: it is neither
        # listed nor removed on its own.
        home = self.get_home()
        reading = self.action in {"content", "thumbnail"}
        stored = services.files_of(home) if reading else services.photos_of(home)
        project = _uuid_param(self.request, "project")
        return stored.filter(project_id=project) if project is not None else stored

    @extend_schema(parameters=[PROJECT_PARAM])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _check_size(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            stored = services.add_file(
                request.user,
                data["project"],
                upload=data["file"],
                quote=data.get("quote"),
                name=data.get("name", ""),
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(stored).data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_file(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={(200, "*/*"): OpenApiTypes.BINARY})
    @action(
        detail=True,
        methods=["get"],
        url_path="content",
        url_name="content",
        renderer_classes=[BinaryRenderer],
    )
    def content(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """The file as stored: images inline, documents as downloads, never sniffed."""
        return file_response(self.get_object())

    @extend_schema(responses={(200, "image/jpeg"): OpenApiTypes.BINARY})
    @action(
        detail=True,
        methods=["get"],
        url_path="thumbnail",
        url_name="thumbnail",
        renderer_classes=[BinaryRenderer],
    )
    def thumbnail(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """The thumbnail of an image."""
        return file_response(self.get_object(), thumbnail=True)


# ---------- links of inspiration ----------


class ProjectLinkSerializer(serializers.ModelSerializer[ProjectLink]):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.none())
    url = serializers.URLField(
        max_length=500,
        help_text="An http or https address. If the instance reads previews, the page is read "
        "once, when the link is added; a page that cannot be read leaves the address alone.",
    )
    title = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        help_text="Empty: the title of the page when it could be read, else empty.",
    )
    image_url = serializers.SerializerMethodField(
        help_text="Address of the picture of the page, kept on this server, or null."
    )
    thumbnail_url = serializers.SerializerMethodField(
        help_text="Address of the thumbnail of that picture, or null."
    )

    class Meta:
        model = ProjectLink
        fields = ["id", "project", "url", "title", "image_url", "thumbnail_url", "created_at"]
        read_only_fields = ["id", "created_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        home = _home(self)
        if home is not None:
            self.fields["project"].queryset = Project.objects.filter(home=home)  # type: ignore[attr-defined]

    def _file_url(self, link: ProjectLink, name: str) -> str | None:
        if link.image_id is None:
            return None
        return str(
            reverse(
                name,
                kwargs={"home_id": link.home_id, "file_id": link.image_id},
                request=self.context["request"],
            )
        )

    @extend_schema_field(OpenApiTypes.URI)
    def get_image_url(self, link: ProjectLink) -> str | None:
        return self._file_url(link, "api-v1:home-project-file-content")

    @extend_schema_field(OpenApiTypes.URI)
    def get_thumbnail_url(self, link: ProjectLink) -> str | None:
        return self._file_url(link, "api-v1:home-project-file-thumbnail")


class ProjectLinkViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[ProjectLink],
):
    """Links of inspiration of the projects of a home. A link is added or removed, not changed.

    When the instance allows previews, adding a link makes the server read the page once to
    find its title and its picture (Open Graph, else the title of the page), under a guard
    that refuses private networks, cloud metadata services and redirects to them, and limits
    size and time. The picture is cleaned like a photo and kept on the server. Whatever goes
    wrong, the link is saved with its address.
    """

    serializer_class = ProjectLinkSerializer
    queryset = ProjectLink.objects.none()
    pagination_class = ProjectPagination
    lookup_field = "id"
    lookup_url_kwarg = "link_id"
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self) -> models.QuerySet[ProjectLink]:
        rows = services.inspiration_links_of(self.get_home())
        project = _uuid_param(self.request, "project")
        return rows.filter(project_id=project) if project is not None else rows

    @extend_schema(parameters=[PROJECT_PARAM])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            link = links.add_link(
                request.user, data["project"], url=data["url"], title=data.get("title", "")
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(link).data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        links.delete_link(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- tasks of a project ----------


class ProjectTaskSerializer(serializers.ModelSerializer[ProjectTask]):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.none())
    task = serializers.PrimaryKeyRelatedField(
        queryset=Task.objects.none(),
        required=False,
        help_text="An existing task of the home that is in no project yet.",
    )
    title = serializers.CharField(
        write_only=True,
        required=False,
        max_length=200,
        help_text="Instead of `task`: the title of a new task, created in the project.",
    )
    due_on = serializers.DateField(write_only=True, required=False, allow_null=True)
    room: serializers.PrimaryKeyRelatedField[Room] = serializers.PrimaryKeyRelatedField(
        write_only=True, required=False, allow_null=True, queryset=Room.objects.none()
    )

    class Meta:
        model = ProjectTask
        fields = ["id", "project", "task", "title", "due_on", "room", "created_at"]
        read_only_fields = ["id", "created_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        home = _home(self)
        if home is not None:
            self.fields["project"].queryset = Project.objects.filter(home=home)  # type: ignore[attr-defined]
            self.fields["task"].queryset = task_services.tasks_of(home)  # type: ignore[attr-defined]
            self.fields["room"].queryset = Room.objects.filter(home=home)  # type: ignore[attr-defined]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if ("task" in attrs) == ("title" in attrs):
            raise serializers.ValidationError("Give either `task` or `title`.")
        return attrs


class ProjectTaskViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[ProjectTask],
):
    """The tasks of the projects of a home. A task is in one project at most.

    Create with `title` to make a new task inside the project, or with `task` to put an
    existing one in. Deleting a row takes the task out of the project; the task stays.
    """

    serializer_class = ProjectTaskSerializer
    queryset = ProjectTask.objects.none()
    pagination_class = ProjectPagination
    lookup_field = "id"
    lookup_url_kwarg = "link_id"
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self) -> models.QuerySet[ProjectTask]:
        links = services.links_of(self.get_home())
        project = _uuid_param(self.request, "project")
        return links.filter(project_id=project) if project is not None else links

    @extend_schema(parameters=[PROJECT_PARAM])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        project = data.pop("project")
        try:
            if "task" in data:
                link = services.attach_task(request.user, project, data["task"])
            else:
                task = services.add_task(request.user, project, **data)
                link = ProjectTask.objects.get(task=task)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(link).data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.detach_task(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- annual envelope ----------


class EnvelopeSerializer(serializers.Serializer[Any]):
    year = serializers.IntegerField()
    envelope = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True, help_text="Null: none set for the year."
    )
    planned = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Planned budget of the projects not finished nor abandoned.",
    )
    paid = serializers.DecimalField(max_digits=14, decimal_places=2)
    left = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        allow_null=True,
        help_text="Envelope less planned; negative: the projects plan more than the envelope.",
    )


class EnvelopeWriteSerializer(serializers.Serializer[Any]):
    year = serializers.IntegerField(required=False)
    amount = MoneyString(**MONEY)


class EnvelopeView(HomeResourceMixin, APIView):
    """What the household wants to spend on work in a year, and what the projects plan."""

    parser_classes = [JSONParser]

    def _year(self, request: Request, given: Any = None) -> int:
        raw = given if given is not None else request.query_params.get("year")
        try:
            return int(raw) if raw is not None else task_services.today().year
        except (TypeError, ValueError):
            raise exceptions.ValidationError({"year": ["Not a valid year."]}) from None

    def _summary(self, request: Request, year: int) -> dict[str, Any]:
        found = services.envelope_summary(self.get_home(), year)
        return {
            "year": found.year,
            "envelope": found.envelope,
            "planned": found.planned,
            "paid": found.paid,
            "left": found.left,
        }

    @extend_schema(
        parameters=[OpenApiParameter("year", int, description="Defaults to this year.")],
        responses=EnvelopeSerializer,
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(EnvelopeSerializer(self._summary(request, self._year(request))).data)

    @extend_schema(request=EnvelopeWriteSerializer, responses=EnvelopeSerializer)
    def put(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Set the envelope of a year (this year if `year` is missing)."""
        home = self.get_home()  # a home that is not mine is a 404 before anything else
        body = EnvelopeWriteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        year = self._year(request, body.validated_data.get("year"))
        try:
            services.set_envelope(
                request.user, home, year=year, amount=body.validated_data["amount"]
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(EnvelopeSerializer(self._summary(request, year)).data)
