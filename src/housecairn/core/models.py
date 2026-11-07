"""Base model shared by every HouseCairn table (docs/adr/0005)."""

import uuid
from typing import Any, ClassVar, Self, TypeVar

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

_M = TypeVar("_M", bound=models.Model)


class SoftDeleteQuerySet(models.QuerySet[_M]):
    def alive(self) -> Self:
        return self.filter(deleted_at__isnull=True)

    def soft_delete(self) -> int:
        return self.update(deleted_at=timezone.now())


class SoftDeleteManager(models.Manager[_M]):
    """Default manager: hides soft-deleted rows."""

    def get_queryset(self) -> SoftDeleteQuerySet[_M]:
        return SoftDeleteQuerySet(self.model, using=self._db).alive()


class BaseModel(models.Model):
    """UUID identifier, timestamps and soft deletion.

    The UUID is the primary key, so no sequential internal identifier exists to
    leak through the API, URLs or QR labels.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)
    deleted_at = models.DateTimeField(_("deleted at"), null=True, blank=True, editable=False)

    # The first manager is the default one: soft-deleted rows are hidden.
    objects: ClassVar[SoftDeleteManager[Any]] = SoftDeleteManager()
    all_objects: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self) -> None:
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])
