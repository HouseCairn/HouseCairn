from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class LabelsConfig(AppConfig):
    name = "housecairn.labels"
    label = "labels"
    verbose_name = _("QR labels")

    def ready(self) -> None:
        from housecairn.labels import exports

        exports.register()
