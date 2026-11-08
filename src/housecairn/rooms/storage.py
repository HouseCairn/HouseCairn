"""Private storage of photos, inside the data volume (docs/adr/0030).

Files live under `MEDIA_ROOT/photos/`, which no URL serves: they leave only through
the views of this app, after the home check.
"""

from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible
from django.utils.functional import cached_property


@deconstructible
class PhotoStorage(FileSystemStorage):
    """`FileSystemStorage` on the current `MEDIA_ROOT`, readable by the service user only."""

    def __init__(self) -> None:
        super().__init__(file_permissions_mode=0o640, directory_permissions_mode=0o750)

    @cached_property
    def base_location(self) -> str:
        return str(Path(settings.MEDIA_ROOT) / "photos")

    @cached_property
    def location(self) -> str:
        return str(Path(self.base_location).resolve())

    @property
    def base_url(self) -> str | None:  # type: ignore[override]
        return None


photo_storage = PhotoStorage()
