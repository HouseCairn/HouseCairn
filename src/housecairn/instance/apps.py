from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class InstanceConfig(AppConfig):
    name = "housecairn.instance"
    label = "instance"
    verbose_name = _("Instance")
