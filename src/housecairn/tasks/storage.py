"""Private storage of attachments, inside the data volume (docs/adr/0034).

Files live under `MEDIA_ROOT/attachments/`, which no URL serves: they leave only
through the views of this app, after the home check.
"""

from pathlib import Path

from django.conf import settings
from django.utils.deconstruct import deconstructible
from django.utils.functional import cached_property

from housecairn.rooms.storage import PhotoStorage


@deconstructible
class AttachmentStorage(PhotoStorage):
    """The storage of photos, in another directory of the same volume."""

    @cached_property
    def base_location(self) -> str:
        return str(Path(settings.MEDIA_ROOT) / "attachments")


attachment_storage = AttachmentStorage()
