"""Photos: content, size, metadata, names, serving and isolation (docs/adr/0030)."""

import io
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse
from PIL import Image

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.rooms import conf, images, services
from housecairn.rooms.models import Item, Photo, Room
from tests.rooms_support import GPS, image_bytes, noise_image, upload

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]


def url(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"rooms:{name}", kwargs={"home_id": home.id, **kwargs})


def stored(photo: Photo) -> bytes:
    with photo.image.open("rb") as handle:
        return handle.read()


class TestContentCheck:
    def test_a_text_file_named_jpg_is_refused(self, alice: User, owner_room: Room) -> None:
        with pytest.raises(ValidationError, match="not a valid"):
            services.add_photo(
                alice, room=owner_room, upload=upload(b"just some text, not an image")
            )
        assert not Photo.objects.exists()

    def test_an_html_or_svg_file_named_png_is_refused(self, alice: User, owner_room: Room) -> None:
        for body in (b"<html><script>alert(1)</script></html>", b"<svg xmlns='x'><script/></svg>"):
            with pytest.raises(ValidationError):
                services.add_photo(
                    alice, room=owner_room, upload=upload(body, "a.png", "image/png")
                )

    def test_the_header_sent_does_not_decide(self, alice: User, owner_room: Room) -> None:
        photo = services.add_photo(
            alice, room=owner_room, upload=upload(image_bytes("PNG"), "x.jpg", "text/html")
        )
        assert photo.content_type == "image/png"

    def test_a_truncated_image_is_refused(self, alice: User, owner_room: Room) -> None:
        with pytest.raises(ValidationError):
            services.add_photo(
                alice, room=owner_room, upload=upload(image_bytes("JPEG", (400, 400))[:300])
            )

    def test_other_image_formats_are_refused(self, alice: User, owner_room: Room) -> None:
        for fmt in ("GIF", "BMP", "TIFF"):
            with pytest.raises(ValidationError):
                services.add_photo(alice, room=owner_room, upload=upload(image_bytes(fmt)))

    def test_an_image_with_too_many_pixels_is_refused(self, alice: User, owner_room: Room) -> None:
        huge = image_bytes("PNG", (8000, 6000), mode="1")
        assert len(huge) < 100_000
        with pytest.raises(ValidationError, match="too large"):
            services.add_photo(alice, room=owner_room, upload=upload(huge, "a.png"))

    def test_an_empty_file_is_refused(self, alice: User, owner_room: Room) -> None:
        with pytest.raises(ValidationError, match="empty"):
            services.add_photo(alice, room=owner_room, upload=upload(b""))

    def test_a_target_is_required_and_only_one(
        self, alice: User, owner_room: Room, owner_item: Item
    ) -> None:
        with pytest.raises(ValueError, match="room or to an item"):
            services.add_photo(alice, upload=upload(image_bytes()))
        with pytest.raises(ValueError, match="room or to an item"):
            services.add_photo(
                alice, room=owner_room, item=owner_item, upload=upload(image_bytes())
            )


class TestSizeLimit:
    def test_a_file_over_the_limit_is_refused(self, alice: User, owner_room: Room) -> None:
        data = noise_image("PNG")
        assert len(data) > conf.MIN_PHOTO_MAX_BYTES
        with (
            override_settings(HOUSECAIRN_PHOTO_MAX_BYTES=len(data) - 1),
            pytest.raises(ValidationError, match="limit"),
        ):
            services.add_photo(alice, room=owner_room, upload=upload(data, "a.png"))
        with override_settings(HOUSECAIRN_PHOTO_MAX_BYTES=len(data)):
            assert services.add_photo(alice, room=owner_room, upload=upload(data, "a.png")).pk

    def test_the_size_is_counted_when_the_sender_declares_none(
        self, alice: User, owner_room: Room
    ) -> None:
        data = noise_image("PNG")
        upload_without_size = SimpleUploadedFile("a.jpg", data)
        upload_without_size.size = None  # type: ignore[assignment]
        with (
            override_settings(HOUSECAIRN_PHOTO_MAX_BYTES=len(data) - 1),
            pytest.raises(ValidationError, match="limit"),
        ):
            services.add_photo(alice, room=owner_room, upload=upload_without_size)

    def test_the_default_limit_and_the_environment(self) -> None:
        from housecairn.instance import registry

        assert conf.photo_max_bytes() == 10 * 1024 * 1024
        # The variable is read when Django starts, like every instance setting (ADR 0042).
        read = registry.read_environment({"HOUSECAIRN_PHOTO_MAX_BYTES": "2000000"})
        assert read.values["file_max_bytes"] == 2_000_000
        assert "file_max_bytes" in read.locked
        with pytest.raises(ImproperlyConfigured, match="HOUSECAIRN_PHOTO_MAX_BYTES"):
            registry.read_environment({"HOUSECAIRN_PHOTO_MAX_BYTES": "5"})

    @pytest.mark.parametrize("value", ["lots", "5", "999999999999"])
    def test_an_unusable_limit_is_an_error(self, value: str) -> None:
        with override_settings(HOUSECAIRN_PHOTO_MAX_BYTES=value):
            with pytest.raises(ImproperlyConfigured):
                conf.photo_max_bytes()
            with pytest.raises(Exception, match="HOUSECAIRN_PHOTO_MAX_BYTES"):
                call_command("check")

    def test_a_photo_count_limit_per_room(
        self, alice: User, owner_room: Room, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(conf, "MAX_PHOTOS_PER_TARGET", 2)
        for _ in range(2):
            services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))
        with pytest.raises(ValidationError, match="At most 2"):
            services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))


class TestMetadata:
    def test_location_is_removed_from_a_jpeg(self, alice: User, owner_room: Room) -> None:
        original = image_bytes("JPEG", gps=True, comment=True)
        before = Image.open(io.BytesIO(original)).getexif()
        assert dict(before.get_ifd(0x8825))  # the test image does carry a location
        photo = services.add_photo(alice, room=owner_room, upload=upload(original))
        data = stored(photo)
        after = Image.open(io.BytesIO(data))
        assert not dict(after.getexif().get_ifd(0x8825))
        assert len(after.getexif()) == 0
        assert b"Exif" not in data[:64]
        assert b"Test camera" not in data
        assert b"secret comment" not in data
        assert "comment" not in after.info

    def test_a_multi_picture_jpeg_is_accepted_as_its_first_image(
        self, alice: User, owner_room: Room
    ) -> None:
        """Phones in portrait or HDR send an MPO: a JPEG with auxiliary images."""
        exif = Image.Exif()
        exif[0x010F] = "Test camera"
        exif[0x8825] = GPS
        buffer = io.BytesIO()
        Image.new("RGB", (64, 48), "red").save(
            buffer,
            format="MPO",
            save_all=True,
            append_images=[Image.new("RGB", (32, 24), "blue")],
            exif=exif,
        )
        original = buffer.getvalue()
        before = Image.open(io.BytesIO(original))
        assert before.format == "MPO"
        assert getattr(before, "n_frames", 1) == 2
        assert dict(before.getexif().get_ifd(0x8825))

        photo = services.add_photo(alice, room=owner_room, upload=upload(original))

        data = stored(photo)
        after = Image.open(io.BytesIO(data))
        assert photo.content_type == "image/jpeg"
        assert after.format == "JPEG"  # a plain JPEG, not an MPO
        assert getattr(after, "n_frames", 1) == 1
        assert after.size == (64, 48)
        assert len(after.getexif()) == 0
        assert not dict(after.getexif().get_ifd(0x8825))
        assert b"Test camera" not in data
        assert b"MPF" not in data  # the multi-picture index is gone

    @pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
    def test_other_formats_keep_nothing_either(
        self, alice: User, owner_room: Room, fmt: str
    ) -> None:
        photo = services.add_photo(
            alice, room=owner_room, upload=upload(image_bytes(fmt, gps=True), f"a.{fmt.lower()}")
        )
        after = Image.open(io.BytesIO(stored(photo)))
        assert after.format == fmt
        assert len(after.getexif()) == 0
        assert b"Test camera" not in stored(photo)

    def test_the_orientation_is_applied_not_kept(self, alice: User, owner_room: Room) -> None:
        # Orientation 6: the image must be turned a quarter; a 64x48 image becomes 48x64.
        photo = services.add_photo(
            alice, room=owner_room, upload=upload(image_bytes("JPEG", (64, 48), orientation=6))
        )
        assert (photo.width, photo.height) == (48, 64)
        assert Image.open(io.BytesIO(stored(photo))).size == (48, 64)

    def test_the_colour_profile_survives(self, alice: User, owner_room: Room) -> None:
        profile = Image.open(io.BytesIO(image_bytes("JPEG"))).info.get("icc_profile")
        assert profile is None  # none in the plain test image: build one with a profile
        from PIL import ImageCms

        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), "red").save(buffer, "JPEG", icc_profile=icc)
        photo = services.add_photo(alice, room=owner_room, upload=upload(buffer.getvalue()))
        assert Image.open(io.BytesIO(stored(photo))).info.get("icc_profile")

    def test_bytes_appended_to_the_file_do_not_survive(self, alice: User, owner_room: Room) -> None:
        payload = b"<script>alert('x')</script>"
        photo = services.add_photo(
            alice, room=owner_room, upload=upload(image_bytes("JPEG") + payload)
        )
        assert payload not in stored(photo)


class TestProcessing:
    def test_a_large_image_is_reduced_and_thumbnailed(self) -> None:
        result = images.process(image_bytes("JPEG", (3000, 2000)))
        assert (result.width, result.height) == (2560, 1707)
        thumbnail = Image.open(io.BytesIO(result.thumbnail))
        assert thumbnail.format == "JPEG"
        assert max(thumbnail.size) == 360

    @pytest.mark.parametrize(
        ("fmt", "mode"),
        [
            ("PNG", "RGBA"),
            ("PNG", "P"),
            ("PNG", "L"),
            ("PNG", "LA"),
            ("PNG", "1"),
            ("WEBP", "RGBA"),
            ("WEBP", "RGB"),
            ("JPEG", "L"),
            ("JPEG", "RGB"),
        ],
    )
    def test_every_mode_is_written_back(self, fmt: str, mode: str) -> None:
        result = images.process(image_bytes(fmt, (40, 30), mode=mode))
        assert Image.open(io.BytesIO(result.data)).format == fmt
        assert Image.open(io.BytesIO(result.thumbnail)).mode == "RGB"

    def test_a_transparent_palette_png_keeps_its_transparency(self) -> None:
        image = Image.new("P", (10, 10), 0)
        image.putpalette([255, 0, 0, 0, 255, 0] + [0] * 250)
        buffer = io.BytesIO()
        image.save(buffer, "PNG", transparency=0)
        result = images.process(buffer.getvalue())
        assert "transparency" in Image.open(io.BytesIO(result.data)).info

    def test_a_cmyk_jpeg_stays_cmyk(self) -> None:
        buffer = io.BytesIO()
        Image.new("CMYK", (20, 20)).save(buffer, "JPEG")
        assert Image.open(io.BytesIO(images.process(buffer.getvalue()).data)).mode == "CMYK"


class TestStorage:
    def test_names_come_from_identifiers_never_from_the_sender(
        self, alice: User, owner_room: Room, media_root: Path
    ) -> None:
        photo = services.add_photo(
            alice,
            room=owner_room,
            upload=upload(image_bytes(), "../../../etc/passwd.jpg"),
            caption="../../evil",
        )
        base = media_root / "photos"
        assert photo.image.name == f"{photo.home_id}/{photo.id}.jpg"
        assert photo.thumbnail.name == f"{photo.home_id}/{photo.id}-thumb.jpg"
        files = sorted(p.relative_to(media_root) for p in media_root.rglob("*") if p.is_file())
        assert [str(f) for f in files] == [
            f"photos/{photo.home_id}/{photo.id}-thumb.jpg",
            f"photos/{photo.home_id}/{photo.id}.jpg",
        ]
        assert all(base in (media_root / f).parents for f in files)
        assert not (media_root.parent / "etc").exists()

    def test_a_failed_save_leaves_no_file(
        self,
        alice: User,
        owner_room: Room,
        media_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken(self: Photo, *args: object, **kwargs: object) -> None:
            raise RuntimeError("database down")

        monkeypatch.setattr(Photo, "save", broken)
        with pytest.raises(RuntimeError):
            services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))
        assert not [p for p in media_root.rglob("*") if p.is_file()]

    def test_photos_of_a_deleted_room_disappear(
        self, alice: User, owner_room: Room, owner_item: Item
    ) -> None:
        services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))
        services.add_photo(alice, item=owner_item, upload=upload(image_bytes()))
        services.delete_room(alice, owner_room)
        assert not Photo.objects.exists()
        assert Photo.all_objects.count() == 2

    def test_update_and_delete(self, alice: User, owner_room: Room) -> None:
        photo = services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))
        services.update_photo(alice, photo, caption="North wall", category="open_walls")
        photo.refresh_from_db()
        assert (photo.caption, photo.category) == ("North wall", "open_walls")
        services.delete_photo(alice, photo)
        assert not Photo.objects.exists()
        assert str(photo) == "North wall"


class TestServing:
    @pytest.fixture
    def photo(self, alice: User, owner_room: Room) -> Photo:
        return services.add_photo(
            alice, room=owner_room, upload=upload(image_bytes("JPEG", gps=True), "../x.jpg")
        )

    def test_the_image_is_sent_as_an_image_and_nothing_else(
        self, signed_in: Client, alice_home: Home, photo: Photo
    ) -> None:
        response = signed_in.get(url("photo", alice_home, photo_id=photo.id))
        assert response.status_code == 200
        assert response["Content-Type"] == "image/jpeg"
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Content-Disposition"] == f'inline; filename="{photo.id}.jpg"'
        assert "script-src" not in response["Content-Security-Policy"]
        assert "sandbox" in response["Content-Security-Policy"]
        assert response["Cache-Control"].startswith("private")
        body = b"".join(response.streaming_content)
        assert Image.open(io.BytesIO(body)).format == "JPEG"
        assert body == stored(photo)

    def test_the_thumbnail(self, signed_in: Client, alice_home: Home, photo: Photo) -> None:
        response = signed_in.get(url("photo-thumbnail", alice_home, photo_id=photo.id))
        assert response["Content-Type"] == "image/jpeg"
        assert response["Content-Disposition"].endswith('.jpg"')
        assert b"".join(response.streaming_content) == photo.thumbnail.open("rb").read()

    def test_each_format_has_its_type_and_name(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room
    ) -> None:
        for fmt, content_type, suffix in (
            ("PNG", "image/png", ".png"),
            ("WEBP", "image/webp", ".webp"),
        ):
            photo = services.add_photo(alice, room=owner_room, upload=upload(image_bytes(fmt)))
            response = signed_in.get(url("photo", alice_home, photo_id=photo.id))
            assert response["Content-Type"] == content_type
            assert response["Content-Disposition"].endswith(f'{suffix}"')

    def test_a_missing_file_is_a_404(
        self, signed_in: Client, alice_home: Home, photo: Photo
    ) -> None:
        Path(photo.image.path).unlink()
        assert signed_in.get(url("photo", alice_home, photo_id=photo.id)).status_code == 404

    def test_sign_in_is_required(self, client: Client, alice_home: Home, photo: Photo) -> None:
        response = client.get(url("photo", alice_home, photo_id=photo.id))
        assert response.status_code == 302

    def test_another_home_cannot_read_it(
        self,
        client: Client,
        bob: User,
        bob_home: Home,
        alice_home: Home,
        photo: Photo,
        site_admin: User,
    ) -> None:
        for who in (bob, site_admin):
            client.force_login(who)
            for home in (alice_home, bob_home):
                for name in ("photo", "photo-thumbnail"):
                    address = url(name, home, photo_id=photo.id)
                    assert client.get(address).status_code == 404, (who, home, name)
                assert client.post(url("photo-delete", home, photo_id=photo.id)).status_code == 404
        assert Photo.objects.filter(id=photo.id).exists()

    def test_a_deleted_photo_is_not_served(
        self, signed_in: Client, alice: User, alice_home: Home, photo: Photo
    ) -> None:
        services.delete_photo(alice, photo)
        assert signed_in.get(url("photo", alice_home, photo_id=photo.id)).status_code == 404


class TestScreens:
    def test_upload_to_a_room_and_an_item(
        self, signed_in: Client, alice_home: Home, owner_room: Room, owner_item: Item
    ) -> None:
        room_form = url("room-photo-add", alice_home, room_id=owner_room.id)
        assert "up to 10" in signed_in.get(room_form).text
        response = signed_in.post(
            room_form,
            {"file": upload(image_bytes()), "caption": "North wall", "category": "open_walls"},
        )
        assert response["Location"] == url("detail", alice_home, room_id=owner_room.id)
        page = signed_in.get(response["Location"])
        assert "North wall" in page.text
        assert "Open walls" in page.text
        item_form = url("item-photo-add", alice_home, item_id=owner_item.id)
        response = signed_in.post(item_form, {"file": upload(image_bytes()), "category": "general"})
        assert response["Location"] == url("item-detail", alice_home, item_id=owner_item.id)
        assert Photo.objects.filter(item=owner_item).count() == 1
        assert "Photo of Boiler" in signed_in.get(response["Location"]).text

    def test_a_bad_upload_shows_the_error(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        response = signed_in.post(
            url("room-photo-add", alice_home, room_id=owner_room.id),
            {"file": upload(b"not an image"), "category": "general"},
        )
        assert response.status_code == 200
        assert "not a valid JPEG, PNG or WebP" in response.text
        assert not Photo.objects.exists()

    def test_an_oversized_upload_is_refused_before_it_is_read(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        with override_settings(HOUSECAIRN_PHOTO_MAX_BYTES=10_240):
            response = signed_in.post(
                url("room-photo-add", alice_home, room_id=owner_room.id),
                data=b"x",
                content_type="multipart/form-data; boundary=x",
                headers={"Content-Length": str(10_240 + conf.MULTIPART_OVERHEAD + 1)},
            )
        assert response.status_code == 413

    def test_delete_a_photo(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room
    ) -> None:
        photo = services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))
        response = signed_in.post(url("photo-delete", alice_home, photo_id=photo.id))
        assert response["Location"] == url("detail", alice_home, room_id=owner_room.id)
        assert not Photo.objects.exists()

    def test_delete_an_item_photo_returns_to_the_item(
        self, signed_in: Client, alice: User, alice_home: Home, owner_item: Item
    ) -> None:
        photo = services.add_photo(alice, item=owner_item, upload=upload(image_bytes()))
        response = signed_in.post(url("photo-delete", alice_home, photo_id=photo.id))
        assert response["Location"] == url("item-detail", alice_home, item_id=owner_item.id)

    def test_read_only_sees_photos_but_cannot_add_or_delete(
        self,
        client: Client,
        alice: User,
        reader: User,
        alice_home: Home,
        owner_room: Room,
    ) -> None:
        photo = services.add_photo(alice, room=owner_room, upload=upload(image_bytes()))
        client.force_login(reader)
        assert client.get(url("photo", alice_home, photo_id=photo.id)).status_code == 200
        page = client.get(url("detail", alice_home, room_id=owner_room.id))
        assert "Add a photo" not in page.text
        assert client.post(url("photo-delete", alice_home, photo_id=photo.id)).status_code == 403
        post = client.post(
            url("room-photo-add", alice_home, room_id=owner_room.id),
            {"file": upload(image_bytes()), "category": "general"},
        )
        assert post.status_code == 403
        assert Photo.objects.count() == 1


def test_a_read_only_member_cannot_add_a_photo(reader: User, owner_room: Room) -> None:
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        services.add_photo(reader, room=owner_room, upload=upload(image_bytes()))
