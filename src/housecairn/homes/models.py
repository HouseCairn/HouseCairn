"""Homes and memberships: every business table hangs off a home (docs/adr/0006)."""

from typing import Any, ClassVar, Self, TypeVar

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
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
    # Identifier of a single sign-on provider declared by the instance
    # administrator; when set, members open this home only in a session signed
    # in through that provider (docs/adr/0021). Empty: no requirement.
    required_provider = models.CharField(
        _("required sign-in provider"), max_length=100, blank=True, default=""
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


class Invitation(BaseModel):
    """An invitation to join a home with a role (docs/adr/0020).

    The link carries a random secret of which only the SHA-256 digest is
    stored, as for API tokens. An invitation is used once: accepted, revoked or
    expired, it opens nothing. Sending it again replaces the secret, so an
    older link stops working.
    """

    home = models.ForeignKey(Home, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField(_("email address"))
    role = models.CharField(_("role"), max_length=16, choices=Role.choices, default=Role.MEMBER)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    digest = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField(_("expires at"))
    sent_at = models.DateTimeField(_("sent at"))
    # True when the link went to the address by email and was shown to nobody:
    # opening it then proves the address belongs to whoever accepts.
    delivered_by_email = models.BooleanField(default=False, editable=False)
    accepted_at = models.DateTimeField(_("accepted at"), null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    revoked_at = models.DateTimeField(_("revoked at"), null=True, blank=True)

    class Meta:
        verbose_name = _("invitation")
        verbose_name_plural = _("invitations")
        constraints = [
            # One invitation at a time per home and address, settled by the
            # database: of two simultaneous requests, one fails. Lapsed ones
            # are revoked when a new invitation is made (services.invite).
            models.UniqueConstraint(
                models.functions.Lower("email"),
                "home",
                condition=models.Q(
                    accepted_at__isnull=True, revoked_at__isnull=True, deleted_at__isnull=True
                ),
                name="unique_pending_invitation",
            )
        ]

    def __str__(self) -> str:
        return f"{self.email} → {self.home} ({self.role})"

    @property
    def is_pending(self) -> bool:
        """Neither accepted, revoked, deleted nor expired."""
        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.deleted_at is None
            and self.expires_at > timezone.now()
        )


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
