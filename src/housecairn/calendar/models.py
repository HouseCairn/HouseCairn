"""Calendar feeds: the secret address a calendar application subscribes to (docs/adr/0052)."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from housecairn.core.models import BaseModel


class Feed(BaseModel):
    """One iCalendar feed of a person: of one home, or of all the homes they open.

    The address carries a random secret of which only the SHA-256 digest is stored, as for
    API tokens: it is shown once, when the feed is created or regenerated. Revoking a feed
    deletes the row, so a revoked secret and a secret that never existed look the same.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="calendar_feeds"
    )
    # None: the combined feed, which follows the person's homes as they change.
    home = models.ForeignKey(
        "homes.Home", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    digest = models.CharField(max_length=64, unique=True, editable=False)
    regenerated_at = models.DateTimeField(_("regenerated at"), null=True, blank=True)

    class Meta:
        verbose_name = _("calendar feed")
        verbose_name_plural = _("calendar feeds")
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "home"],
                condition=models.Q(home__isnull=False),
                name="one_calendar_feed_per_home",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(home__isnull=True),
                name="one_combined_calendar_feed",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.home_id or 'combined'}"
