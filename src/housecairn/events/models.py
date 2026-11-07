"""Inbound events (sensor readings, integration notifications), per home."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from housecairn.homes.models import HomeOwnedModel


class Event(HomeOwnedModel):
    kind = models.SlugField(_("kind"), max_length=64)
    payload = models.JSONField(_("payload"), default=dict, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    token = models.ForeignKey(
        "apitokens.ApiToken", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = _("event")
        verbose_name_plural = _("events")

    def __str__(self) -> str:
        return self.kind
