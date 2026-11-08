from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class RoomsConfig(AppConfig):
    name = "housecairn.rooms"
    label = "rooms"
    verbose_name = _("Rooms")

    def ready(self) -> None:
        from housecairn.rooms import checks  # noqa: F401 - registers the system check
