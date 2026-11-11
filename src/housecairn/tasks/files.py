"""Which files may be attached to a task, and sending one back (docs/adr/0034).

Images go through `housecairn.rooms.images` as they are, as photos do. Other files
are accepted from an allow-list, decided by their content: the name and the header
sent by the client are never read. A file is stored as is (it is not rewritten), so
it is only ever sent back as a download, with a type fixed by this module.
"""

import io
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.utils.translation import gettext as _

from housecairn.rooms import conf
from housecairn.tasks.models import Attachment

NAME_MAX_LENGTH = 120
# A document unpacked is never larger than this: a zip built to fill the disk when opened.
MAX_UNPACKED_FACTOR = 20
MAX_ZIP_ENTRIES = 5000


@dataclass(frozen=True)
class FileKind:
    content_type: str
    extension: str


PDF = FileKind("application/pdf", ".pdf")
TEXT = FileKind("text/plain; charset=utf-8", ".txt")
DOCX = FileKind("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")
XLSX = FileKind("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")
ODT = FileKind("application/vnd.oasis.opendocument.text", ".odt")
ODS = FileKind("application/vnd.oasis.opendocument.spreadsheet", ".ods")
ACCEPTED = (PDF, TEXT, DOCX, XLSX, ODT, ODS)
# What the file chooser offers; the content is checked all the same.
ACCEPT_ATTRIBUTE = "image/jpeg,image/png,image/webp,.pdf,.txt,.docx,.xlsx,.odt,.ods"


def _refused() -> ValidationError:
    return ValidationError(
        _(
            "This type of file is not accepted. Use a JPEG, PNG or WebP image, "
            "or a PDF, text, Word, Excel or OpenDocument file."
        )
    )


# The brands of the box that opens a HEIC or HEIF file (an iPhone photo in its default format).
_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1")


def _is_heif(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS


def _zip_kind(data: bytes) -> FileKind | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                return None
            if (
                sum(entry.file_size for entry in entries)
                > MAX_UNPACKED_FACTOR * conf.photo_max_bytes()
            ):
                return None
            names = {entry.filename for entry in entries}
            if "[Content_Types].xml" in names:
                if "word/document.xml" in names:
                    return DOCX
                if "xl/workbook.xml" in names:
                    return XLSX
                return None
            # OpenDocument: the first entry, `mimetype`, is stored and names the type.
            if entries and entries[0].filename == "mimetype" and entries[0].file_size < 100:
                mimetype = archive.read("mimetype")
                for kind in (ODT, ODS):
                    if mimetype == kind.content_type.encode():
                        return kind
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError, RuntimeError):
        return None
    return None


def _is_text(data: bytes) -> bool:
    """UTF-8 without control characters (but the tab and the line breaks): not a program."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return not any(unicodedata.category(ch) == "Cc" and ch not in "\t\n\r\f" for ch in text)


def detect(data: bytes) -> FileKind:
    """The kind of a file that is not an image; ValidationError when it is not on the list."""
    kind: FileKind | None = None
    if _is_heif(data):
        raise ValidationError(
            _(
                "HEIC photos are not accepted. Choose the JPEG version of the photo, "
                "or set the camera to Most Compatible."
            )
        )
    if data.startswith(b"%PDF-"):
        kind = PDF
    elif data.startswith(b"PK\x03\x04"):
        kind = _zip_kind(data)
    elif _is_text(data):
        kind = TEXT
    if kind is None:
        raise _refused()
    return kind


def clean_name(raw: str | None, fallback: str = "file") -> str:
    """A name fit to show: no folder, no control or direction character, at most 120 long."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(
        ch for ch in name if unicodedata.category(ch) not in {"Cc", "Cf", "Cs", "Co", "Cn"}
    ).strip(" .")
    if len(name) > NAME_MAX_LENGTH:
        stem, dot, extension = name.rpartition(".")
        name = (stem[: NAME_MAX_LENGTH - len(extension) - 1] + dot + extension) if dot else name
        name = name[:NAME_MAX_LENGTH]
    return name or fallback


def attachment_response(attachment: Attachment, *, thumbnail: bool = False) -> FileResponse:
    """The stored file or the thumbnail of an image.

    Images are shown inline, everything else is a download. The type comes from the
    content found at upload; the name is the identifier. `nosniff` stops a browser
    from guessing another type and the policy forbids any script or frame.
    """
    if thumbnail and not attachment.thumbnail:
        raise Http404
    stored = attachment.thumbnail if thumbnail else attachment.file
    content_type = "image/jpeg" if thumbnail else attachment.content_type
    extension = ".jpg" if thumbnail else _extension(attachment)
    try:
        handle = stored.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404 from None
    response = FileResponse(handle, content_type=content_type)
    inline = attachment.is_image
    response["Content-Disposition"] = (
        f'{"inline" if inline else "attachment"}; filename="{attachment.id}{extension}"'
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, max-age=3600"
    return response


def _extension(attachment: Attachment) -> str:
    return PurePosixPath(attachment.file.name).suffix
