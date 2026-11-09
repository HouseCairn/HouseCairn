"""Private storage of the photos of reports, inside the data volume (docs/adr/0047).

Files live under `MEDIA_ROOT/reports/<home id>/`, which no URL serves: they leave only
through the views of this app, after the home check.
"""

from pathlib import Path

from django.conf import settings
from django.utils.deconstruct import deconstructible
from django.utils.functional import cached_property

from housecairn.rooms.storage import PhotoStorage


@deconstructible
class ReportStorage(PhotoStorage):
    """The storage of photos, in another directory of the same volume."""

    @cached_property
    def base_location(self) -> str:
        return str(Path(settings.MEDIA_ROOT) / "reports")


report_storage = ReportStorage()
