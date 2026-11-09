"""QR labels are part of the export of their home (docs/adr/0023, 0047).

The code of an active label is exported, so that the stickers already stuck on the walls
still open the right page if the home is ever restored; the code of a revoked label is
not, it opens nothing.
"""

from typing import Any

from housecairn.homes import exports
from housecairn.homes.models import Home
from housecairn.labels.models import Label


def _labels(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(label.id),
            "kind": label.kind,
            "target": str(label.target_id),
            "code": label.code if label.revoked_at is None else None,
            "revoked_at": label.revoked_at.isoformat() if label.revoked_at else None,
            "created_at": label.created_at.isoformat(),
        }
        for label in Label.objects.filter(home=home).order_by("created_at", "id")
    ]


def register() -> None:
    exports.register("labels", _labels)
