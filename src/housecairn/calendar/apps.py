from django.apps import AppConfig
from django.db.models.signals import post_save
from django.utils.translation import gettext_lazy as _


class CalendarConfig(AppConfig):
    name = "housecairn.calendar"
    label = "calendar"
    verbose_name = _("Calendar")

    def ready(self) -> None:
        from housecairn.audit.models import AuditEvent
        from housecairn.calendar import feeds
        from housecairn.calendar.models import Feed
        from housecairn.homes import exports
        from housecairn.homes.models import Membership

        post_save.connect(feeds.membership_saved, sender=Membership, dispatch_uid="calendar-leave")
        post_save.connect(
            feeds.departure_recorded, sender=AuditEvent, dispatch_uid="calendar-departure"
        )
        # That a feed exists and when, never its address or the digest of its secret
        # (docs/adr/0052); a restore does not bring a feed back, its owner makes a new one.
        exports.register(
            "calendar",
            exports.Section(
                "calendar_feeds",
                Feed,
                exclude=("digest",),
                restore=False,
                why_not_restored="the address of a feed is a secret that is not kept",
            ),
        )
