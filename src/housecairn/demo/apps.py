from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


class DemoConfig(AppConfig):
    name = "housecairn.demo"
    label = "demo"
    verbose_name = _("Demonstration")

    def ready(self) -> None:
        from housecairn.demo import admin, guards, tasks

        guards.connect()
        admin.read_only()
        post_migrate.connect(tasks.schedule, sender=self)
