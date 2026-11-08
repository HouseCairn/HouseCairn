"""Attachments of tasks: content, size, metadata, names, serving, isolation (docs/adr/0034)."""

import io
import json
import logging
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.rooms import conf
from housecairn.tasks import files, services
from housecairn.tasks.models import MAX_ATTACHMENTS_PER_TASK, Attachment, Occurrence, Task
from housecairn.tasks.storage import attachment_storage
from tests.rooms_support import GPS, image_bytes, noise_image, upload
from tests.tasks_fixtures import PDF

pytest_plugins = ("tests.tasks_fixtures",)
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]


def url(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"tasks:{name}", kwargs={"home_id": home.id, **kwargs})


def zipped(entries: dict[str, bytes], *, first: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if first is not None:
            archive.writestr("mimetype", first, compress_type=zipfile.ZIP_STORED)
        for name, data in entries.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


DOCX = zipped({"[Content_Types].xml": b"<x/>", "word/document.xml": b"<w/>"})
XLSX = zipped({"[Content_Types].xml": b"<x/>", "xl/workbook.xml": b"<w/>"})
ODT = zipped({"content.xml": b"<c/>"}, first="application/vnd.oasis.opendocument.text")
ODS = zipped({"content.xml": b"<c/>"}, first="application/vnd.oasis.opendocument.spreadsheet")


def path_of(attachment: Attachment) -> Path:
    return Path(attachment.file.path)


def stored(attachment: Attachment) -> bytes:
    with attachment.file.open("rb") as handle:
        return handle.read()


class TestContentCheck:
    @pytest.mark.parametrize(
        ("data", "content_type", "extension"),
        [
            (PDF, "application/pdf", ".pdf"),
            (b"Torque: 12 Nm\nBrand: Acme\n", "text/plain; charset=utf-8", ".txt"),
            ("Chaudière, révision à 90 €".encode(), "text/plain; charset=utf-8", ".txt"),
            (DOCX, files.DOCX.content_type, ".docx"),
            (XLSX, files.XLSX.content_type, ".xlsx"),
            (ODT, files.ODT.content_type, ".odt"),
            (ODS, files.ODS.content_type, ".ods"),
        ],
    )
    def test_documents_on_the_list_are_accepted(
        self, alice: User, owner_task: Task, data: bytes, content_type: str, extension: str
    ) -> None:
        attachment = services.add_attachment(alice, owner_task, upload=upload(data, "x.bin", "x/y"))
        assert (attachment.content_type, attachment.is_image) == (content_type, False)
        assert attachment.file.name.endswith(extension)
        assert stored(attachment) == data
        assert not attachment.thumbnail

    @pytest.mark.parametrize(
        "data",
        [
            b"MZ\x90\x00\x03\x00\x00\x00 an executable",
            b"\x7fELF\x02\x01\x01 a program",
            b"GIF89a\x01\x00\x01\x00",
            b"\x00\x01\x02 binary with a NUL",
            b"\xff\xfe\xfd not utf-8 \xc3\x28",
            zipped({"a.txt": b"hello"}),
            zipped({"[Content_Types].xml": b"<x/>", "ppt/presentation.xml": b"<p/>"}),
            zipped({"content.xml": b"<c/>"}, first="application/x-evil"),
            b"PK\x03\x04 not really a zip",
        ],
    )
    def test_anything_else_is_refused(self, alice: User, owner_task: Task, data: bytes) -> None:
        with pytest.raises(ValidationError, match="not accepted"):
            services.add_attachment(
                alice, owner_task, upload=upload(data, "photo.jpg", "image/jpeg")
            )
        assert not Attachment.objects.exists()

    def test_the_name_and_the_header_do_not_decide(self, alice: User, owner_task: Task) -> None:
        pdf = services.add_attachment(alice, owner_task, upload=upload(PDF, "p.jpg", "image/jpeg"))
        assert pdf.content_type == "application/pdf"
        png = services.add_attachment(
            alice, owner_task, upload=upload(image_bytes("PNG"), "x.pdf", "application/pdf")
        )
        assert (png.content_type, png.is_image) == ("image/png", True)

    def test_a_broken_image_is_refused_with_the_image_message(
        self, alice: User, owner_task: Task
    ) -> None:
        with pytest.raises(ValidationError, match="not a valid JPEG"):
            services.add_attachment(
                alice, owner_task, upload=upload(image_bytes("JPEG", (400, 400))[:300])
            )

    def test_a_zip_that_unpacks_to_too_much_is_refused(
        self, alice: User, owner_task: Task, settings: object
    ) -> None:
        settings.HOUSECAIRN_PHOTO_MAX_BYTES = conf.MIN_PHOTO_MAX_BYTES  # type: ignore[attr-defined]
        big = zipped(
            {
                "[Content_Types].xml": b"<x/>",
                "word/document.xml": b"0" * (21 * conf.MIN_PHOTO_MAX_BYTES),
            }
        )
        assert len(big) < conf.MIN_PHOTO_MAX_BYTES
        with pytest.raises(ValidationError, match="not accepted"):
            services.add_attachment(alice, owner_task, upload=upload(big))

    def test_an_empty_file_is_refused(self, alice: User, owner_task: Task) -> None:
        with pytest.raises(ValidationError, match="empty"):
            services.add_attachment(alice, owner_task, upload=upload(b""))


class TestSize:
    def test_a_file_over_the_limit_is_refused(
        self, alice: User, owner_task: Task, settings: object
    ) -> None:
        settings.HOUSECAIRN_PHOTO_MAX_BYTES = conf.MIN_PHOTO_MAX_BYTES  # type: ignore[attr-defined]
        with pytest.raises(ValidationError, match="too large"):
            services.add_attachment(
                alice, owner_task, upload=upload(PDF + b"0" * conf.MIN_PHOTO_MAX_BYTES)
            )
        with pytest.raises(ValidationError, match="too large"):
            services.add_attachment(alice, owner_task, upload=upload(noise_image("PNG", 100)))
        assert not Attachment.objects.exists()

    def test_the_size_is_counted_when_the_sender_declares_none(
        self, alice: User, owner_task: Task, settings: object
    ) -> None:
        settings.HOUSECAIRN_PHOTO_MAX_BYTES = conf.MIN_PHOTO_MAX_BYTES  # type: ignore[attr-defined]
        liar = SimpleUploadedFile("a.pdf", PDF + b"0" * conf.MIN_PHOTO_MAX_BYTES)
        liar.size = None  # type: ignore[assignment]
        with pytest.raises(ValidationError, match="too large"):
            services.add_attachment(alice, owner_task, upload=liar)

    def test_a_count_limit_per_task(self, alice: User, owner_task: Task) -> None:
        for number in range(MAX_ATTACHMENTS_PER_TASK):
            services.add_attachment(alice, owner_task, upload=upload(f"note {number}".encode()))
        with pytest.raises(ValidationError, match="At most"):
            services.add_attachment(alice, owner_task, upload=upload(b"one more"))


class TestImages:
    def test_location_is_removed_and_the_thumbnail_is_made(
        self, alice: User, owner_task: Task
    ) -> None:
        original = image_bytes("JPEG", (200, 100), gps=True, comment=True)
        assert Image.open(io.BytesIO(original)).getexif().get_ifd(0x8825) == GPS
        attachment = services.add_attachment(alice, owner_task, upload=upload(original))
        assert (attachment.is_image, attachment.content_type) == (True, "image/jpeg")
        assert (attachment.width, attachment.height) == (200, 100)
        kept = Image.open(io.BytesIO(stored(attachment)))
        assert not kept.getexif()
        assert b"secret comment" not in stored(attachment)
        assert attachment.thumbnail
        assert Image.open(attachment.thumbnail.open("rb")).format == "JPEG"

    def test_an_image_can_be_attached_to_an_occurrence(
        self, alice: User, owner_task: Task, owner_occurrence: Occurrence
    ) -> None:
        attachment = services.add_attachment(
            alice, owner_task, upload=upload(image_bytes()), occurrence=owner_occurrence
        )
        assert attachment.occurrence_id == owner_occurrence.id

    def test_an_occurrence_of_another_task_is_refused(
        self, alice: User, alice_home: Home, owner_task: Task, owner_occurrence: Occurrence
    ) -> None:
        other = services.create_task(alice, alice_home, title="other")
        with pytest.raises(ValidationError):
            services.add_attachment(
                alice, other, upload=upload(image_bytes()), occurrence=owner_occurrence
            )


class TestNames:
    @pytest.mark.parametrize(
        ("raw", "shown"),
        [
            ("../../etc/passwd", "passwd"),
            ("..\\..\\windows\\system32\\config.pdf", "config.pdf"),
            ("<b>bold</b>.pdf", "b>.pdf"),
            ("<img src=x onerror=alert(1)>.pdf", "<img src=x onerror=alert(1)>.pdf"),
            ("invoice\u202egpj.pdf", "invoicegpj.pdf"),
            ("bad\x00name\r\n.txt", "badname.txt"),
            ("   ...   ", "file"),
            ("", "file"),
            ("é" * 300 + ".pdf", "é" * 116 + ".pdf"),
        ],
    )
    def test_clean_name(self, raw: str, shown: str) -> None:
        assert files.clean_name(raw) == shown

    def test_a_hostile_name_never_reaches_the_disk_or_a_header(
        self, signed_in: Client, alice: User, alice_home: Home, owner_task: Task, media_root: Path
    ) -> None:
        attachment = services.add_attachment(
            alice, owner_task, upload=upload(PDF, '../../../etc/cron.d/x"; filename="y.pdf')
        )
        assert attachment.file.name == f"{alice_home.id}/{attachment.id}.pdf"
        assert (media_root / "attachments" / attachment.file.name).is_file()
        assert not list(media_root.rglob("cron*"))
        response = signed_in.get(url("attachment", alice_home, attachment_id=attachment.id))
        assert response["Content-Disposition"] == f'attachment; filename="{attachment.id}.pdf"'

    def test_the_name_is_escaped_on_the_page(
        self, signed_in: Client, alice: User, alice_home: Home, owner_task: Task
    ) -> None:
        services.add_attachment(
            alice, owner_task, upload=upload(PDF, "<img src=x onerror=alert(1)>.pdf")
        )
        page = signed_in.get(url("detail", alice_home, task_id=owner_task.id)).content.decode()
        assert "<img src=x onerror" not in page
        assert "&lt;img src=x onerror=alert(1)&gt;.pdf" in page

    def test_rename(self, alice: User, owner_task: Task) -> None:
        attachment = services.add_attachment(alice, owner_task, upload=upload(PDF))
        services.update_attachment(alice, attachment, name="../Boiler manual.pdf")
        attachment.refresh_from_db()
        assert attachment.name == "Boiler manual.pdf"


class TestServing:
    @pytest.fixture
    def document(self, alice: User, owner_task: Task) -> Attachment:
        return services.add_attachment(alice, owner_task, upload=upload(PDF, "manual.pdf"))

    @pytest.fixture
    def picture(self, alice: User, owner_task: Task) -> Attachment:
        return services.add_attachment(
            alice, owner_task, upload=upload(image_bytes("PNG"), "x.png")
        )

    def test_a_document_is_a_download_of_a_fixed_type(
        self, signed_in: Client, alice_home: Home, document: Attachment
    ) -> None:
        response = signed_in.get(url("attachment", alice_home, attachment_id=document.id))
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response["Content-Disposition"].startswith("attachment;")
        assert response["X-Content-Type-Options"] == "nosniff"
        assert "sandbox" in response["Content-Security-Policy"]
        assert b"".join(response.streaming_content) == PDF

    def test_text_is_served_as_plain_text_never_as_a_page(
        self, signed_in: Client, alice: User, alice_home: Home, owner_task: Task
    ) -> None:
        html = services.add_attachment(
            alice,
            owner_task,
            upload=upload(b"<html><script>alert(1)</script></html>", "a.html", "text/html"),
        )
        response = signed_in.get(url("attachment", alice_home, attachment_id=html.id))
        assert response["Content-Type"].startswith("text/plain")
        assert response["Content-Disposition"].startswith("attachment;")
        assert response["X-Content-Type-Options"] == "nosniff"

    def test_an_image_is_inline_and_has_a_thumbnail(
        self, signed_in: Client, alice_home: Home, picture: Attachment
    ) -> None:
        response = signed_in.get(url("attachment", alice_home, attachment_id=picture.id))
        assert response["Content-Type"] == "image/png"
        assert response["Content-Disposition"].startswith("inline;")
        thumb = signed_in.get(url("attachment-thumbnail", alice_home, attachment_id=picture.id))
        assert thumb["Content-Type"] == "image/jpeg"

    def test_a_document_has_no_thumbnail(
        self, signed_in: Client, alice_home: Home, document: Attachment
    ) -> None:
        assert (
            signed_in.get(
                url("attachment-thumbnail", alice_home, attachment_id=document.id)
            ).status_code
            == 404
        )

    def test_a_missing_file_is_a_404(
        self, signed_in: Client, alice_home: Home, document: Attachment
    ) -> None:
        Path(document.file.path).unlink()
        assert (
            signed_in.get(url("attachment", alice_home, attachment_id=document.id)).status_code
            == 404
        )

    def test_sign_in_is_required(
        self, client: Client, alice_home: Home, document: Attachment
    ) -> None:
        response = client.get(url("attachment", alice_home, attachment_id=document.id))
        assert response.status_code == 302

    def test_another_home_and_the_instance_administrator_cannot_read_it(
        self,
        client: Client,
        bob: User,
        bob_home: Home,
        alice_home: Home,
        document: Attachment,
        site_admin: User,
    ) -> None:
        for who in (bob, site_admin):
            client.force_login(who)
            for home in (alice_home, bob_home):
                for name in ("attachment", "attachment-thumbnail"):
                    assert client.get(url(name, home, attachment_id=document.id)).status_code == 404
                assert (
                    client.post(
                        url("attachment-delete", home, attachment_id=document.id)
                    ).status_code
                    == 404
                )
        assert Attachment.objects.filter(id=document.id).exists()

    def test_a_deleted_attachment_or_task_is_not_served(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        owner_task: Task,
        document: Attachment,
    ) -> None:
        services.delete_task(alice, owner_task)
        assert (
            signed_in.get(url("attachment", alice_home, attachment_id=document.id)).status_code
            == 404
        )

    def test_the_files_are_outside_every_public_address(
        self, media_root: Path, document: Attachment
    ) -> None:
        assert (media_root / "attachments").is_dir()
        assert str(media_root / "attachments") in document.file.path


class TestScreens:
    def test_add_files_to_a_task(
        self, signed_in: Client, alice_home: Home, owner_task: Task
    ) -> None:
        address = url("attachment-add", alice_home, task_id=owner_task.id)
        assert signed_in.get(address).status_code == 200
        response = signed_in.post(
            address,
            {
                "uploads": [
                    upload(PDF, "a.pdf"),
                    upload(image_bytes(), "b.jpg"),
                    upload(b"note", "c.txt"),
                ]
            },
        )
        assert response.status_code == 302
        assert Attachment.objects.filter(task=owner_task).count() == 3
        page = signed_in.get(url("detail", alice_home, task_id=owner_task.id)).content.decode()
        assert "a.pdf" in page
        assert "<img" in page

    def test_a_bad_file_shows_its_error_and_the_good_ones_stay(
        self, signed_in: Client, alice_home: Home, owner_task: Task
    ) -> None:
        response = signed_in.post(
            url("attachment-add", alice_home, task_id=owner_task.id),
            {"uploads": [upload(PDF, "good.pdf"), upload(b"MZ\x90\x00", "evil.exe")]},
        )
        assert response.status_code == 200
        assert "evil.exe" in response.content.decode()
        assert "not accepted" in response.content.decode()
        assert Attachment.objects.filter(task=owner_task).count() == 1

    def test_no_file_is_an_error(
        self, signed_in: Client, alice_home: Home, owner_task: Task
    ) -> None:
        response = signed_in.post(url("attachment-add", alice_home, task_id=owner_task.id), {})
        assert response.status_code == 200
        assert "Choose at least one file" in response.content.decode()

    def test_an_oversized_body_is_refused_before_it_is_read(
        self, signed_in: Client, alice_home: Home, owner_task: Task
    ) -> None:
        with override_settings(HOUSECAIRN_PHOTO_MAX_BYTES=conf.MIN_PHOTO_MAX_BYTES):
            response = signed_in.post(
                url("attachment-add", alice_home, task_id=owner_task.id),
                data=b"x",
                content_type="multipart/form-data; boundary=x",
                headers={
                    "Content-Length": str(
                        6 * conf.MIN_PHOTO_MAX_BYTES + conf.MULTIPART_OVERHEAD + 1
                    )
                },
            )
        assert response.status_code == 413

    def test_files_can_be_joined_when_the_task_is_created(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        response = signed_in.post(
            url("create", alice_home),
            {
                "title": "Fit the shelf",
                "priority": "normal",
                "repeat_mode": "once",
                "repeat_interval": "1",
                "repeat_unit": "month",
                "hide_days_before": "0",
                "uploads": [upload(image_bytes(), "before.jpg"), upload(b"MZ\x90", "bad.exe")],
            },
        )
        assert response.status_code == 302
        task = Task.objects.get(title="Fit the shelf")
        assert task.attachments.count() == 1
        followed = signed_in.get(response["Location"]).content.decode()
        assert "bad.exe" in followed
        assert "File not added" in followed

    def test_delete(
        self,
        signed_in: Client,
        alice_home: Home,
        alice: User,
        owner_task: Task,
        django_capture_on_commit_callbacks: Callable[..., Any],
    ) -> None:
        attachment = services.add_attachment(alice, owner_task, upload=upload(PDF))
        assert path_of(attachment).is_file()
        with django_capture_on_commit_callbacks(execute=True):
            response = signed_in.post(
                url("attachment-delete", alice_home, attachment_id=attachment.id)
            )
        assert response.status_code == 302
        assert not Attachment.objects.filter(id=attachment.id).exists()
        assert Attachment.all_objects.filter(id=attachment.id).exists()
        assert not path_of(attachment).exists()

    def test_read_only_sees_the_files_and_cannot_add_or_delete(
        self, client: Client, reader: User, alice: User, alice_home: Home, owner_task: Task
    ) -> None:
        attachment = services.add_attachment(alice, owner_task, upload=upload(PDF, "manual.pdf"))
        client.force_login(reader)
        page = client.get(url("detail", alice_home, task_id=owner_task.id)).content.decode()
        assert "manual.pdf" in page
        assert "attachments/new" not in page
        assert (
            client.get(url("attachment", alice_home, attachment_id=attachment.id)).status_code
            == 200
        )
        assert (
            client.get(url("attachment-add", alice_home, task_id=owner_task.id)).status_code == 403
        )
        assert (
            client.post(
                url("attachment-delete", alice_home, attachment_id=attachment.id)
            ).status_code
            == 403
        )
        assert Attachment.objects.filter(id=attachment.id).exists()


class TestRoles:
    def test_read_only_cannot_attach(self, reader: User, owner_task: Task) -> None:
        from django.core.exceptions import PermissionDenied

        with pytest.raises(PermissionDenied):
            services.add_attachment(reader, owner_task, upload=upload(PDF))

    def test_a_failed_save_leaves_no_file(
        self, alice: User, owner_task: Task, media_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(self: Attachment, *args: object, **kwargs: object) -> None:
            raise RuntimeError("disk full")

        monkeypatch.setattr(Attachment, "save", boom)
        with pytest.raises(RuntimeError):
            services.add_attachment(alice, owner_task, upload=upload(image_bytes()))
        assert not [p for p in media_root.rglob("*") if p.is_file()]


def delete_home(actor: User, home: Home, name: str) -> None:
    with TestCase.captureOnCommitCallbacks(execute=True):
        home_services.delete_home(actor, home, confirmation=name)


class TestErasure:
    def test_deleting_an_image_erases_the_file_and_its_thumbnail(
        self, alice: User, owner_task: Task
    ) -> None:
        picture = services.add_attachment(alice, owner_task, upload=upload(image_bytes("PNG")))
        file, thumbnail = Path(picture.file.path), Path(picture.thumbnail.path)
        assert file.is_file()
        assert thumbnail.is_file()
        with TestCase.captureOnCommitCallbacks(execute=True):
            services.delete_attachment(alice, picture)
        assert not file.exists()
        assert not thumbnail.exists()

    def test_nothing_is_erased_before_the_deletion_is_committed(
        self, alice: User, owner_task: Task
    ) -> None:
        document = services.add_attachment(alice, owner_task, upload=upload(PDF))
        services.delete_attachment(alice, document)
        assert path_of(document).is_file()

    def test_deleting_a_task_erases_its_files_and_only_those(
        self, alice: User, owner_task: Task, alice_home: Home
    ) -> None:
        other = services.create_task(alice, alice_home, title="Other")
        mine = services.add_attachment(alice, owner_task, upload=upload(PDF))
        kept = services.add_attachment(alice, other, upload=upload(PDF))
        with TestCase.captureOnCommitCallbacks(execute=True):
            services.delete_task(alice, owner_task)
        assert not path_of(mine).exists()
        assert path_of(kept).is_file()

    def test_a_failure_to_erase_is_logged_and_does_not_raise(
        self, alice: User, owner_task: Task, caplog: pytest.LogCaptureFixture
    ) -> None:
        document = services.add_attachment(alice, owner_task, upload=upload(PDF))
        with (
            caplog.at_level(logging.ERROR, logger="housecairn.tasks.services"),
            mock.patch.object(attachment_storage, "delete", side_effect=OSError("disk")),
            TestCase.captureOnCommitCallbacks(execute=True),
        ):
            services.delete_attachment(alice, document)
        assert "Could not erase" in caplog.text
        assert not Attachment.objects.filter(id=document.id).exists()

    def test_the_files_go_with_the_home_and_not_those_of_another(
        self,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        owner_task: Task,
        media_root: Path,
    ) -> None:
        mine = services.add_attachment(alice, owner_task, upload=upload(PDF))
        theirs_task = services.create_task(bob, bob_home, title="Theirs")
        theirs = services.add_attachment(bob, theirs_task, upload=upload(PDF))
        services.delete_attachment(
            alice, services.add_attachment(alice, owner_task, upload=upload(PDF))
        )
        mine_dir = media_root / "attachments" / str(alice_home.id)
        assert path_of(mine).is_file()
        delete_home(alice, alice_home, "Main house")
        assert not mine_dir.exists()
        assert path_of(theirs).is_file()


class TestExport:
    def export(self, client: Client, actor: User, home: Home) -> zipfile.ZipFile:
        client.force_login(actor)
        response = client.post(reverse("homes:export", kwargs={"home_id": home.id}))
        assert response.status_code == 200
        return zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))

    def test_attachments_and_their_files_are_in_the_archive(
        self,
        client: Client,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        owner_task: Task,
        owner_occurrence: Occurrence,
    ) -> None:
        document = services.add_attachment(alice, owner_task, upload=upload(PDF, "manual.pdf"))
        picture = services.add_attachment(
            alice,
            owner_task,
            upload=upload(image_bytes("PNG", gps=True), "label.png"),
            occurrence=owner_occurrence,
        )
        gone = services.add_attachment(alice, owner_task, upload=upload(PDF, "gone.pdf"))
        services.delete_attachment(alice, gone)
        theirs_task = services.create_task(bob, bob_home, title="Secret task")
        services.add_attachment(bob, theirs_task, upload=upload(PDF, "secret.pdf"))

        archive = self.export(client, alice, alice_home)
        data = json.loads(archive.read("export.json"))
        by_id = {a["id"]: a for a in data["attachments"]}
        assert set(by_id) == {str(document.id), str(picture.id)}
        assert by_id[str(document.id)]["name"] == "manual.pdf"
        assert by_id[str(document.id)]["task"] == str(owner_task.id)
        assert by_id[str(picture.id)]["occurrence"] == str(owner_occurrence.id)
        assert by_id[str(picture.id)]["is_image"] is True
        for attachment in (document, picture):
            path = by_id[str(attachment.id)]["file"]
            assert path.startswith("files/attachments/")
            assert archive.read(path) == stored(attachment)
        assert by_id[str(document.id)]["file"].endswith(".pdf")
        assert b"Exif" not in archive.read(by_id[str(picture.id)]["file"])
        raw = archive.read("export.json").decode()
        for secret in ("secret.pdf", "Secret task", "gone.pdf", str(bob_home.id)):
            assert secret not in raw
        assert not any(str(bob_home.id) in n for n in archive.namelist())

    def test_a_missing_file_leaves_the_record_without_a_path(
        self, client: Client, alice: User, alice_home: Home, owner_task: Task
    ) -> None:
        document = services.add_attachment(alice, owner_task, upload=upload(PDF))
        path_of(document).unlink()
        data = json.loads(self.export(client, alice, alice_home).read("export.json"))
        assert data["attachments"][0]["file"] is None
        assert data["files"] == []

    def test_a_stored_name_outside_the_home_folder_is_never_read(
        self,
        client: Client,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        owner_task: Task,
    ) -> None:
        theirs_task = services.create_task(bob, bob_home, title="Theirs")
        theirs = services.add_attachment(bob, theirs_task, upload=upload(PDF))
        mine = services.add_attachment(alice, owner_task, upload=upload(PDF))
        for name in (
            f"../{bob_home.id}/{Path(theirs.file.name).name}",
            f"{bob_home.id}/{Path(theirs.file.name).name}",
            "../../../../etc/passwd",
            "/etc/passwd",
        ):
            Attachment.objects.filter(pk=mine.pk).update(file=name)
            archive = self.export(client, alice, alice_home)
            data = json.loads(archive.read("export.json"))
            assert data["attachments"][0]["file"] is None, name
            assert data["files"] == [], name
