from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


class NotificationsConfig(AppConfig):
    name = "housecairn.notifications"
    label = "notifications"
    verbose_name = _("Notifications")

    def ready(self) -> None:
        from housecairn.notifications import outbound, tasks

        outbound.install()
        post_migrate.connect(tasks.schedule, sender=self)
