from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BudgetConfig(AppConfig):
    """Figures only: no table of its own, so nothing to export or erase (docs/adr/0051)."""

    name = "housecairn.budget"
    label = "budget"
    verbose_name = _("Budget")
