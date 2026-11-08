"""Export of rooms and photos, erasure of their files with the home (docs/adr/0036)."""

import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

import pytest
from django.test import Client, TestCase
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes import files
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.rooms import services
from housecairn.rooms.models import Photo, Room
from tests.rooms_support import image_bytes, upload

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = pytest.mark.django_db


def add_photo(actor: User, **target: Any) -> Photo:
    return services.add_photo(actor, upload=upload(image_bytes(gps=True)), **target)


def delete_home(actor: User, home: Home, name: str) -> None:
    with TestCase.captureOnCommitCallbacks(execute=True):
        home_services.delete_home(actor, home, confirmation=name)


class TestEraseFilesWithTheHome:
    def test_photo_files_go_with_the_home_and_not_those_of_another(
        self,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        media_root: Path,
    ) -> None:
        mine = add_photo(alice, room=services.create_room(alice, alice_home, name="Kitchen"))
        theirs = add_photo(bob, room=services.create_room(bob, bob_home, name="Hall"))
        mine_dir = media_root / "photos" / str(alice_home.id)
        assert (mine_dir / Path(mine.image.name).name).is_file()
        delete_home(alice, alice_home, "Main house")
        assert not mine_dir.exists()
        assert (media_root / "photos" / str(bob_home.id) / Path(theirs.image.name).name).is_file()

    def test_a_soft_deleted_photo_goes_too(
        self, alice: User, alice_home: Home, owner_room: Room, media_root: Path
    ) -> None:
        photo = add_photo(alice, room=owner_room)
        services.delete_photo(alice, photo)
        assert (media_root / "photos" / str(alice_home.id)).exists()
        delete_home(alice, alice_home, "Main house")
        assert not (media_root / "photos" / str(alice_home.id)).exists()

    def test_a_link_is_removed_and_never_followed(
        self, alice: User, alice_home: Home, media_root: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "precious.txt").write_text("keep")
        (media_root / "photos").mkdir(parents=True)
        (media_root / "photos" / str(alice_home.id)).symlink_to(outside, target_is_directory=True)
        delete_home(alice, alice_home, "Main house")
        assert not (media_root / "photos" / str(alice_home.id)).exists()
        assert (outside / "precious.txt").read_text() == "keep"

    def test_a_link_inside_the_directory_is_not_followed(
        self, alice: User, alice_home: Home, media_root: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "precious.txt").write_text("keep")
        directory = media_root / "photos" / str(alice_home.id)
        directory.mkdir(parents=True)
        (directory / "trap").symlink_to(outside, target_is_directory=True)
        delete_home(alice, alice_home, "Main house")
        assert not directory.exists()
        assert (outside / "precious.txt").read_text() == "keep"

    def test_a_failure_is_logged_and_the_home_is_still_deleted(
        self,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        media_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        add_photo(alice, room=owner_room)

        def refuse(path: Any) -> None:
            raise PermissionError("denied")

        monkeypatch.setattr(files.shutil, "rmtree", refuse)
        with caplog.at_level(logging.ERROR, logger="housecairn.files"):
            delete_home(alice, alice_home, "Main house")
        assert not Home.all_objects.filter(pk=alice_home.pk).exists()
        assert str(alice_home.id) in caplog.text
        assert "denied" not in caplog.text

    def test_a_directory_that_resolves_elsewhere_is_refused(
        self, alice_home: Home, media_root: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        folder = media_root / "photos"
        folder.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        folder_real = folder.resolve()
        assert folder_real.parent == media_root.resolve()
        with pytest.raises(ValueError, match="directly in its folder"):
            files._erase(outside, folder)

    def test_other_apps_can_declare_their_folder(
        self, alice: User, alice_home: Home, media_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(files, "MEDIA_FOLDERS", list(files.MEDIA_FOLDERS))
        files.register_media_folder("attachments")
        files.register_media_folder("attachments")
        directory = media_root / "attachments" / str(alice_home.id)
        directory.mkdir(parents=True)
        (directory / "plan.pdf").write_bytes(b"%PDF")
        delete_home(alice, alice_home, "Main house")
        assert not directory.exists()


class TestExportRooms:
    def export(self, client: Client, actor: User, home: Home) -> zipfile.ZipFile:
        client.force_login(actor)
        response = client.post(reverse("homes:export", kwargs={"home_id": home.id}))
        assert response.status_code == 200
        return zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))

    def test_rooms_items_memory_and_photos_are_in_the_archive(
        self,
        client: Client,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        media_root: Path,
    ) -> None:
        room = services.create_room(
            alice,
            alice_home,
            name="Living room",
            kind="living",
            paint_colour="Sage",
            paint_reference="RAL 6021",
            memory_notes="Two coats",
        )
        item = services.create_item(
            alice,
            room,
            name="Boiler",
            brand="Acme",
            warranty_ends_on="2031-09-14",
            links=[{"url": "https://example.com/manual", "label": "Manual"}],
        )
        room_photo = add_photo(alice, room=room, caption="Wall")
        item_photo = add_photo(alice, item=item)
        gone = add_photo(alice, room=room, caption="Deleted")
        services.delete_photo(alice, gone)
        other_room = services.create_room(bob, bob_home, name="Secret room")
        services.create_item(bob, other_room, name="Secret item")
        add_photo(bob, room=other_room, caption="Secret photo")

        archive = self.export(client, alice, alice_home)
        data = json.loads(archive.read("export.json"))
        assert [r["name"] for r in data["rooms"]] == ["Living room"]
        assert data["rooms"][0]["id"] == str(room.id)
        assert data["rooms"][0]["memory"]["paint_colour"] == "Sage"
        assert data["rooms"][0]["memory"]["memory_notes"] == "Two coats"
        assert [i["name"] for i in data["items"]] == ["Boiler"]
        assert data["items"][0]["room"] == str(room.id)
        assert data["items"][0]["warranty_ends_on"] == "2031-09-14"
        assert data["items"][0]["links"][0]["url"] == "https://example.com/manual"
        by_id = {p["id"]: p for p in data["photos"]}
        assert set(by_id) == {str(room_photo.id), str(item_photo.id)}
        assert by_id[str(room_photo.id)]["room"] == str(room.id)
        assert by_id[str(room_photo.id)]["caption"] == "Wall"
        assert by_id[str(item_photo.id)]["item"] == str(item.id)
        names = set(archive.namelist())
        for photo in (room_photo, item_photo):
            path = by_id[str(photo.id)]["file"]
            assert path in names
            assert archive.read(path) == photo.image.read()
        assert {f["path"] for f in data["files"]} == {by_id[k]["file"] for k in by_id}
        raw = archive.read("export.json").decode()
        for secret in ("Secret room", "Secret item", "Secret photo", str(bob_home.id)):
            assert secret not in raw
        assert not any(str(bob_home.id) in n for n in names)

    def test_exported_photos_carry_no_location(
        self, client: Client, alice: User, alice_home: Home, owner_room: Room, media_root: Path
    ) -> None:
        photo = add_photo(alice, room=owner_room)
        archive = self.export(client, alice, alice_home)
        path = json.loads(archive.read("export.json"))["photos"][0]["file"]
        assert b"Exif" not in archive.read(path)
        assert photo.id

    def test_a_missing_file_leaves_the_record_without_a_path(
        self, client: Client, alice: User, alice_home: Home, owner_room: Room, media_root: Path
    ) -> None:
        photo = add_photo(alice, room=owner_room)
        Path(photo.image.path).unlink()
        data = json.loads(self.export(client, alice, alice_home).read("export.json"))
        assert data["photos"][0]["file"] is None
        assert data["files"] == []

    def test_a_stored_name_outside_the_home_folder_is_never_read(
        self,
        client: Client,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        owner_room: Room,
        media_root: Path,
    ) -> None:
        bob_photo = add_photo(bob, room=services.create_room(bob, bob_home, name="Hall"))
        mine = add_photo(alice, room=owner_room)
        for name in (
            f"../{bob_home.id}/{Path(bob_photo.image.name).name}",
            f"{bob_home.id}/{Path(bob_photo.image.name).name}",
            "../../../../etc/passwd",
            "/etc/passwd",
        ):
            Photo.objects.filter(pk=mine.pk).update(image=name)
            archive = self.export(client, alice, alice_home)
            data = json.loads(archive.read("export.json"))
            assert data["photos"][0]["file"] is None
            assert not any(n.startswith("files/photos/") for n in archive.namelist())
