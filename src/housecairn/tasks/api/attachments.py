"""API v1 of task attachments (docs/adr/0034)."""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse

from housecairn.rooms import conf
from housecairn.rooms.api import (
    BinaryRenderer,
    HomeResourceMixin,
    PayloadTooLarge,
    _uuid_param,
    _validation,
)
from housecairn.tasks import files, services
from housecairn.tasks.models import (
    Attachment,
    Occurrence,
    Task,
)


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
