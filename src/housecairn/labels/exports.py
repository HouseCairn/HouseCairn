"""QR labels in the export of their home (docs/adr/0047, 0048).

The code of an active label is exported, so that the stickers already stuck on the walls
still open the right page once the home is restored; the code of a revoked label is not,
it opens nothing, and a restore gives the revoked label a new random code. A copy of the
home gives every label a new code: the stickers keep opening the home they were printed
for (docs/adr/0069).
"""

from typing import Any

from django.db import models

from housecairn.homes import exports
from housecairn.labels.models import Label, new_code


def _hide_revoked_code(label: models.Model, data: dict[str, Any]) -> dict[str, Any]:
    if data.get("revoked_at") is not None:
        data["code"] = None
    return data


def _code_for_revoked(data: dict[str, Any], home: Any) -> dict[str, Any]:
    if data.get("code") is None and data.get("revoked_at") is not None:
        data["code"] = new_code()
    return data


def _new_code(data: dict[str, Any], home: Any) -> dict[str, Any]:
    data["code"] = new_code()
    return data


def register() -> None:
    exports.register(
        "labels",
        exports.Section(
            "labels",
            Label,
            on_export=_hide_revoked_code,
            on_restore=_code_for_revoked,
            on_copy=_new_code,
            nulls=("code",),
        ),
    )
