"""Rooms, items, room memory and photos are part of the export of their home (docs/adr/0023, 0036).

Plain objects with identifiers and dates as text. The files of the photos go into
`files/photos/`, already stripped of their metadata at upload (docs/adr/0030);
thumbnails are not exported, they are made again from the photo.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from django.core.exceptions import SuspiciousFileOperation

from housecairn.homes import exports
from housecairn.homes.models import Home
from housecairn.rooms.files import EXTENSIONS
from housecairn.rooms.models import Item, Photo, Room
from housecairn.rooms.storage import photo_storage

MEMORY_FIELDS = (
    "paint_colour",
    "paint_brand",
    "paint_reference",
    "paint_batch",
    "floor_covering",
    "wall_covering",
    "memory_notes",
)


def _rooms(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "kind": r.kind,
            "position": r.position,
            "notes": r.notes,
            "memory": {
                **{name: getattr(r, name) for name in MEMORY_FIELDS},
                "paint_article": str(r.paint_article_id) if r.paint_article_id else None,
            },
            "created_at": r.created_at.isoformat(),
        }
        for r in Room.objects.filter(home=home).order_by("position", "created_at", "id")
    ]


def _items(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(i.id),
            "room": str(i.room_id),
            "name": i.name,
            "kind": i.kind,
            "brand": i.brand,
            "model": i.model,
            "serial_number": i.serial_number,
            "installed_on": i.installed_on.isoformat() if i.installed_on else None,
            "warranty_ends_on": i.warranty_ends_on.isoformat() if i.warranty_ends_on else None,
            "contract_provider": i.contract_provider,
            "contract_number": i.contract_number,
            "contract_url": i.contract_url,
            "links": i.links,
            "notes": i.notes,
            "created_at": i.created_at.isoformat(),
        }
        for i in Item.objects.filter(home=home).order_by("created_at", "id")
    ]


def _archive_name(photo: Photo) -> str:
    return f"photos/{photo.id}{EXTENSIONS.get(photo.content_type, '')}"


def _stored_file(photo: Photo) -> Path | None:
    """The photo on disk, if it is there and inside the folder of its own home."""
    try:
        path = Path(photo_storage.path(photo.image.name)).resolve()
    except (SuspiciousFileOperation, ValueError, OSError):
        return None
    folder = (Path(photo_storage.location) / str(photo.home_id)).resolve()
    if path.parent != folder or not path.is_file():
        return None
    return path


def _photos(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(p.id),
            "room": str(p.room_id) if p.room_id else None,
            "item": str(p.item_id) if p.item_id else None,
            "category": p.category,
            "caption": p.caption,
            "content_type": p.content_type,
            "size_bytes": p.size_bytes,
            "width": p.width,
            "height": p.height,
            "file": f"files/{_archive_name(p)}" if _stored_file(p) else None,
            "created_at": p.created_at.isoformat(),
        }
        for p in Photo.objects.filter(home=home).order_by("created_at", "id")
    ]


def _files(home: Home) -> Iterator[exports.ExportedFile]:
    for photo in Photo.objects.filter(home=home).order_by("created_at", "id"):
        source = _stored_file(photo)
        if source is not None:
            yield exports.ExportedFile(name=_archive_name(photo), source=source)


def register() -> None:
    exports.register("rooms", _rooms)
    exports.register("items", _items)
    exports.register("photos", _photos)
    exports.register_files(_files)
