"""API tokens: scoped, bound to homes, expiring, revocable, stored hashed (docs/adr/0007)."""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from housecairn.core.models import BaseModel


class Scope(models.TextChoices):
    READ = "read", _("Read")
    WRITE = "write", _("Write")
    EVENTS = "events", _("Post events")


class ApiToken(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens"
    )
    name = models.CharField(_("name"), max_length=100)
    # Only the SHA-256 digest of the secret is stored; the prefix helps the user
    # recognise a token in a list.
    prefix = models.CharField(_("prefix"), max_length=12, editable=False)
    digest = models.CharField(max_length=64, unique=True, editable=False)
    scopes = models.JSONField(_("scopes"), default=list)
    homes = models.ManyToManyField("homes.Home", related_name="+", verbose_name=_("homes"))
    expires_at = models.DateTimeField(_("expires at"), null=True, blank=True)
    revoked_at = models.DateTimeField(_("revoked at"), null=True, blank=True)
    last_used_at = models.DateTimeField(_("last used at"), null=True, blank=True)

    class Meta:
        verbose_name = _("API token")
        verbose_name_plural = _("API tokens")

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…)"

    @property
    def is_active(self) -> bool:
        now = timezone.now()
        return (
            self.revoked_at is None
            and self.deleted_at is None
            and (self.expires_at is None or self.expires_at > now)
        )

    def has_scope(self, scope: Scope) -> bool:
        return scope.value in self.scopes
