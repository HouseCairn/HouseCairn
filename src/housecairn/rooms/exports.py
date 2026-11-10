"""Rooms, items, room memory and photos in the export of their home (docs/adr/0036, 0048).

The photos go into `files/photos/`, as stored: already stripped of their metadata at upload
(docs/adr/0030). Thumbnails are not exported; a restore makes them again from the photo.
"""

from housecairn.homes import exports
from housecairn.rooms.models import Item, Photo, Room


def register() -> None:
    exports.register(
        "rooms",
        exports.Section("rooms", Room, order_by=("position", "created_at", "id")),
        exports.Section("items", Item),
        exports.Section(
            "photos",
            Photo,
            files=(exports.FileSpec("image", "photos", thumbnail="thumbnail"),),
        ),
    )
