"""Spike check, run inside a candidate image by `manage shell -c` (no shell needed).

Creates a throwaway account, home and room, uploads one JPEG, PNG and WebP
photo through the service layer (Pillow decodes and writes them again, as for
a real upload), reads the stored image and its thumbnail back with Pillow, and
prints one line `SPIKE-PHOTO <json>` with what was read and the database used.
"""

import io
import json
import sys
import uuid

import PIL
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from PIL import Image

from housecairn.accounts.models import User
from housecairn.homes.services import create_home
from housecairn.rooms import services

user = User.objects.create_user(email=f"spike-{uuid.uuid4().hex[:8]}@example.com", password=None)
home = create_home(user, name="Spike home")
room = services.create_room(user, home, name="Spike room")
result: dict[str, object] = {"database": connection.vendor, "pillow": PIL.__version__}
for fmt, ext in (("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp")):
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 900), (31, 58, 61)).save(buffer, fmt)
    upload = SimpleUploadedFile(f"spike.{ext}", buffer.getvalue(), content_type="image/x-spike")
    photo = services.add_photo(user, upload=upload, room=room)
    with photo.image.open("rb") as stored:
        image = Image.open(stored)
        image.load()
    with photo.thumbnail.open("rb") as stored:
        thumbnail = Image.open(stored)
        thumbnail.load()
    result[fmt] = {
        "stored": image.format,
        "size": list(image.size),
        "thumbnail": [thumbnail.format, *thumbnail.size],
    }
sys.stdout.write("SPIKE-PHOTO " + json.dumps(result, sort_keys=True) + "\n")
