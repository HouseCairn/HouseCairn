"""Private storage of the photos and quote files of projects, in the data volume (docs/adr/0050).

Files live under `MEDIA_ROOT/projects/<home id>/`, which no URL serves: they leave only
through the views of this app, after the home check.
"""

from pathlib import Path

from django.conf import settings
from django.utils.deconstruct import deconstructible
from django.utils.functional import cached_property

from housecairn.rooms.storage import PhotoStorage


@deconstructible
class ProjectStorage(PhotoStorage):
    """The storage of photos, in another directory of the same volume."""

    @cached_property
    def base_location(self) -> str:
        return str(Path(settings.MEDIA_ROOT) / "projects")


project_storage = ProjectStorage()
