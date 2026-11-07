from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class HomesConfig(AppConfig):
    name = "housecairn.homes"
    label = "homes"
    verbose_name = _("Homes")
