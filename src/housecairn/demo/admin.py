"""The administration site of a demonstration instance is read only (docs/adr/0071).

Its screens show the accounts and the tokens, and change none of them: no add, no change, no
delete, whatever the model, and not by the action "delete selected" either. Two layers, the
first for what the site shows and the second for what a request could still send:

- `read_only` takes the three permissions away from every model administration, so that the
  site shows no button and no form field to change;
- `AdminReadOnlyMiddleware` (`demo.middleware`) refuses any request of the site that is not a
  read, apart from signing in and out.

Off a demonstration instance both do nothing.
"""

from collections.abc import Callable
from typing import Any

from django.contrib.admin.options import BaseModelAdmin
from django.http import HttpRequest
from django.utils.translation import gettext as _

from housecairn.demo import mode

_PERMISSIONS = ("has_add_permission", "has_change_permission", "has_delete_permission")

# What the site does with a POST that is not a change: signing in and signing out.
ALLOWED_URL_NAMES = frozenset({"login", "logout"})


def admin_message() -> str:
    return _("This is a demonstration instance: the administration site can be read, not changed.")


def _read_only(original: Callable[..., bool]) -> Callable[..., bool]:
    def has_permission(self: BaseModelAdmin[Any], request: HttpRequest, *args: Any) -> bool:
        return False if mode.is_on() else original(self, request, *args)

    has_permission.__name__ = original.__name__
    has_permission._demo_read_only = True  # type: ignore[attr-defined]
    return has_permission


def read_only() -> None:
    """Wrap the permissions of every model administration, once."""
    for name in _PERMISSIONS:
        original = getattr(BaseModelAdmin, name)
        if not getattr(original, "_demo_read_only", False):
            setattr(BaseModelAdmin, name, _read_only(original))
