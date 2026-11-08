from django.apps import AppConfig
from django.db.models.signals import post_save
from django.utils.translation import gettext_lazy as _


class CalendarConfig(AppConfig):
    name = "housecairn.calendar"
    label = "calendar"
    verbose_name = _("Calendar")

    def ready(self) -> None:
        from housecairn.calendar import feeds
        from housecairn.homes import exports
        from housecairn.homes.models import Membership

        post_save.connect(feeds.membership_saved, sender=Membership, dispatch_uid="calendar-leave")
        exports.register("calendar_feeds", feeds.export_of)
