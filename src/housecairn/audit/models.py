"""Audit log of sensitive operations (docs/adr/0023).

An entry says who did what, to whom, when, never what a home contains: the
values it may carry (`detail`) are a role, a provider identifier, a count.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Scope(models.TextChoices):
    HOME = "home", _("Home")
    INSTANCE = "instance", _("Instance")


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(_("date"), auto_now_add=True, db_index=True)
    scope = models.CharField(max_length=16, choices=Scope.choices)
    action = models.CharField(_("action"), max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # The home of a home-scope entry. Not a foreign key: the entries of a home
    # are deleted with it (services.delete_home), and an entry never keeps a
    # home alive or hides its deletion.
    home_id = models.UUIDField(null=True, blank=True, db_index=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("audit entry")
        verbose_name_plural = _("audit entries")
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=["scope", "-created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(scope="home", home_id__isnull=False)
                    | models.Q(scope="instance", home_id__isnull=True)
                ),
                name="audit_scope_matches_home",
            )
        ]

    def __str__(self) -> str:
        return f"{self.action} ({self.scope})"

    @property
    def label(self) -> str:
        from housecairn.audit.labels import label

        return label(self.action, self.detail)
