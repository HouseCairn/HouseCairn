"""Reports in the export of their home (docs/adr/0047, 0048).

The photos go into `files/reports/`, already stripped of their metadata at upload;
thumbnails are not exported, a restore makes them again from the photo.
"""

from housecairn.homes import exports
from housecairn.reports.models import Report


def register() -> None:
    exports.register(
        "reports",
        exports.Section(
            "reports",
            Report,
            files=(
                exports.FileSpec(
                    "photo", "reports", content_type="photo_content_type", thumbnail="thumbnail"
                ),
            ),
        ),
    )
