"""API v1 of reports. Validation only; rules live in `services`."""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.http.response import HttpResponseBase
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse

from housecairn.homes.models import Home
from housecairn.reports import services
from housecairn.reports.files import photo_response
from housecairn.reports.models import (
    CLOSED_STATUSES,
    TITLE_MAX_LENGTH,
    Report,
    ReportStatus,
)
from housecairn.rooms import conf
from housecairn.rooms.api import BinaryRenderer, HomeResourceMixin, PayloadTooLarge, _validation
from housecairn.rooms.models import Item, Room
from housecairn.stock.models import Article


class ReportSerializer(serializers.ModelSerializer[Report]):
    reporter_name = serializers.SerializerMethodField(
        help_text="Who reported, by display name; never an e-mail address."
    )
    mine = serializers.SerializerMethodField(help_text="True when the caller made the report.")
    room = serializers.UUIDField(source="room_id", read_only=True, allow_null=True)
    item = serializers.UUIDField(source="item_id", read_only=True, allow_null=True)
    article = serializers.UUIDField(source="article_id", read_only=True, allow_null=True)
    task = serializers.UUIDField(
        source="task_id", read_only=True, allow_null=True, help_text="The task made from it."
    )
    photo_url = serializers.SerializerMethodField(help_text="Address of the photo, or null.")
    thumbnail_url = serializers.SerializerMethodField(
        help_text="Address of its thumbnail, or null."
    )

    class Meta:
        model = Report
        fields = [
            "id",
            "title",
            "status",
            "place",
            "room",
            "item",
            "article",
            "task",
            "reporter_name",
            "mine",
            "photo_url",
            "thumbnail_url",
            "created_at",
            "closed_at",
        ]
        read_only_fields = fields

    def get_reporter_name(self, report: Report) -> str:
        # A list gives the labels of the whole page (two people of one name are told apart);
        # a single report is named alone.
        shown = self.context.get("reporter_labels") or services.reporter_labels([report])
        return str(shown[report.id])

    def get_mine(self, report: Report) -> bool:
        return bool(report.reporter_id == self.context["request"].user.pk)

    def _url(self, name: str, report: Report) -> str:
        return str(
            reverse(
                name,
                kwargs={"home_id": report.home_id, "report_id": report.id},
                request=self.context["request"],
            )
        )

    @extend_schema_field(OpenApiTypes.URI)
    def get_photo_url(self, report: Report) -> str | None:
        return self._url("api-v1:home-report-photo", report) if report.has_photo else None

    @extend_schema_field(OpenApiTypes.URI)
    def get_thumbnail_url(self, report: Report) -> str | None:
        return self._url("api-v1:home-report-thumbnail", report) if report.has_photo else None


class ReportCreateSerializer(serializers.Serializer[Any]):
    title = serializers.CharField(max_length=TITLE_MAX_LENGTH, help_text="What is wrong.")
    room: serializers.PrimaryKeyRelatedField[Room] = serializers.PrimaryKeyRelatedField(
        queryset=Room.objects.none(), required=False, help_text="Where: a room of the home."
    )
    item: serializers.PrimaryKeyRelatedField[Item] = serializers.PrimaryKeyRelatedField(
        queryset=Item.objects.none(), required=False, help_text="Where: an item of the home."
    )
    article: serializers.PrimaryKeyRelatedField[Article] = serializers.PrimaryKeyRelatedField(
        queryset=Article.objects.none(), required=False, help_text="Where: a stock item."
    )
    photo = serializers.FileField(
        required=False, help_text="A JPEG, PNG or WebP photo, checked by its content."
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        home: Home | None = self.context.get("home")
        if home is not None:
            self.fields["room"].queryset = Room.objects.filter(home=home)  # type: ignore[attr-defined]
            self.fields["item"].queryset = Item.objects.filter(home=home)  # type: ignore[attr-defined]
            self.fields["article"].queryset = Article.objects.filter(home=home)  # type: ignore[attr-defined]


class CloseSerializer(serializers.Serializer[Any]):
    resolution = serializers.ChoiceField(
        choices=[(s.value, s.label) for s in CLOSED_STATUSES],
        help_text="`resolved` or `no_action` (closed without action).",
    )


class ReportViewSet(
    HomeResourceMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet[Report],
):
    """Problems reported in a home. Every member reports, a read-only one included, and
    sees the reports they made; a member who writes sees them all, makes one into a task,
    closes it and reopens it. The photo is sent as `multipart/form-data` (`photo`)."""

    serializer_class = ReportSerializer
    queryset = Report.objects.none()
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    lookup_field = "id"
    lookup_url_kwarg = "report_id"
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self) -> models.QuerySet[Report]:
        reports = services.visible_reports(self.request.user, self.get_home())
        status_filter = self.request.query_params.get("status")
        if status_filter == "closed":
            reports = reports.filter(status__in=CLOSED_STATUSES)
        elif status_filter:
            reports = reports.filter(status=status_filter)
        if self.request.query_params.get("mine", "").lower() in {"1", "true"}:
            reports = reports.filter(reporter_id=self.request.user.pk)
        return reports

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                str,
                enum=[*ReportStatus.values, "closed"],
                description="`closed` is resolved or closed without action.",
            ),
            OpenApiParameter("mine", bool, description="True: only the reports of the caller."),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        found = list(page) if page is not None else list(queryset)
        serializer = self.get_serializer(
            found,
            many=True,
            context={
                **self.get_serializer_context(),
                "reporter_labels": services.reporter_labels(found),
            },
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(
        request={"multipart/form-data": ReportCreateSerializer},
        responses={201: ReportSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        home = self.get_home()
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
        if declared > conf.photo_max_bytes() + conf.MULTIPART_OVERHEAD:
            raise PayloadTooLarge
        serializer = ReportCreateSerializer(data=request.data, context={"home": home})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            report = services.create_report(
                request.user,
                home,
                title=data["title"],
                room=data.get("room"),
                item=data.get("item"),
                article=data.get("article"),
                photo=data.get("photo"),
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        fresh = services.reports_of(home).get(pk=report.pk)
        return Response(self.get_serializer(fresh).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: ReportSerializer})
    @action(detail=True, methods=["post"], url_path="task", url_name="task")
    def to_task(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Make the report into a task with no date; `task` then holds its identifier."""
        report = self.get_object()
        try:
            services.make_task(request.user, report)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(
            self.get_serializer(services.reports_of(report.home).get(pk=report.pk)).data
        )

    @extend_schema(request=CloseSerializer, responses={200: ReportSerializer})
    @action(detail=True, methods=["post"], url_path="close", url_name="close")
    def close(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Close the report as `resolved` or `no_action`."""
        report = self.get_object()
        serializer = CloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.close_report(
                request.user, report, resolution=serializer.validated_data["resolution"]
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(
            self.get_serializer(services.reports_of(report.home).get(pk=report.pk)).data
        )

    @extend_schema(request=None, responses={200: ReportSerializer})
    @action(detail=True, methods=["post"], url_path="reopen", url_name="reopen")
    def reopen(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Reopen a closed report; it goes back to its task if it had one."""
        report = self.get_object()
        try:
            services.reopen_report(request.user, report)
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(
            self.get_serializer(services.reports_of(report.home).get(pk=report.pk)).data
        )

    @extend_schema(responses={(200, "image/*"): OpenApiTypes.BINARY})
    @action(
        detail=True,
        methods=["get"],
        url_path="photo",
        url_name="photo",
        renderer_classes=[BinaryRenderer],
    )
    def photo(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """The photo, as stored: JPEG, PNG or WebP, served inline and never sniffed."""
        return photo_response(self.get_object())

    @extend_schema(responses={(200, "image/jpeg"): OpenApiTypes.BINARY})
    @action(
        detail=True,
        methods=["get"],
        url_path="photo/thumbnail",
        url_name="thumbnail",
        renderer_classes=[BinaryRenderer],
    )
    def thumbnail(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """The thumbnail of the photo, a JPEG."""
        return photo_response(self.get_object(), thumbnail=True)
