"""Homes and memberships: every business table hangs off a home (docs/adr/0006)."""

from typing import Any, ClassVar, Self, TypeVar

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from housecairn.core.models import BaseModel, SoftDeleteManager, SoftDeleteQuerySet

_M = TypeVar("_M", bound=models.Model)


class Role(models.TextChoices):
    OWNER = "owner", _("Owner")
    MEMBER = "member", _("Member")
    READ_ONLY = "read_only", _("Read only")


WRITE_ROLES = frozenset({Role.OWNER, Role.MEMBER})


class Home(BaseModel):
    name = models.CharField(_("name"), max_length=120)
    currency = models.CharField(
        _("currency"),
        max_length=3,
        default="EUR",
        validators=[RegexValidator(r"^[A-Z]{3}$", _("Use an ISO 4217 code, such as EUR."))],
        help_text=_("ISO 4217 code of the currency used for this home's budget."),
    )

    class Meta:
        verbose_name = _("home")
        verbose_name_plural = _("homes")

    def __str__(self) -> str:
        return self.name


class Membership(BaseModel):
    home = models.ForeignKey(Home, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(_("role"), max_length=16, choices=Role.choices, default=Role.MEMBER)

    class Meta:
        verbose_name = _("membership")
        verbose_name_plural = _("memberships")
        constraints = [
            models.UniqueConstraint(
                fields=["home", "user"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_membership",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.home} ({self.role})"


class HomeOwnedQuerySet(SoftDeleteQuerySet[_M]):
    def in_homes(self, homes: models.QuerySet[Home]) -> Self:
        return self.filter(home__in=homes)


class HomeOwnedManager(SoftDeleteManager[_M]):
    def get_queryset(self) -> HomeOwnedQuerySet[_M]:
        return HomeOwnedQuerySet(self.model, using=self._db).alive()

    def in_homes(self, homes: models.QuerySet[Home]) -> HomeOwnedQuerySet[_M]:
        return self.get_queryset().in_homes(homes)


class HomeOwnedModel(BaseModel):
    """Base for every business model: belongs to exactly one home."""

    home = models.ForeignKey(Home, on_delete=models.CASCADE, related_name="+")

    objects: ClassVar[HomeOwnedManager[Any]] = HomeOwnedManager()

    class Meta:
        abstract = True
