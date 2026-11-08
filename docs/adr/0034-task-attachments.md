# 0034. Photos and files attached to tasks

- Status: accepted
- Date: 2026-11-08

## Context

A task is easier to do with the photo of the label, the manual of the machine, a
quote in PDF. Uploads are untrusted input (ADR 0030): a file named `.pdf` can be
anything, a name can climb out of a directory or carry markup, and a stored document
can run in a browser if it is served as a page.

## Decision

**One table**, `Attachment`: a task, optionally one of its occurrences (the photo
taken when it was done), a displayed name, the stored file, a thumbnail for an image,
the type found, the size.

**Images go through `housecairn.rooms.images.process`, imported as it is**: type by
content (JPEG, PNG, WebP), size in pixels checked before decoding, orientation
applied, metadata and location dropped, thumbnail made (ADR 0030). The processing was
not moved to a shared module: nothing in it needed to change, so the two apps share a
dependency rather than a refactoring of rooms.

**Other files are accepted from an allow-list, decided by content** (`tasks/files.py`):
PDF (starts with `%PDF-`), plain text (valid UTF-8 without control characters, so a
program is not "text"), Word and Excel (a zip holding the parts that name the type,
`word/document.xml` or `xl/workbook.xml`), OpenDocument text and spreadsheet (first
entry `mimetype` naming the type). A zip is never unpacked; it is refused above 5,000
entries or an unpacked size over 20 times the upload limit. The type sent by the client
and the extension are never read; a file of another type (an executable, GIF, HEIC) is
refused with a message.

**Stored as received, sent back as a download.** A document is not rewritten, so it
is never shown inline: `Content-Disposition: attachment`, a content type fixed by this
module (text is `text/plain`, never `text/html`), `X-Content-Type-Options: nosniff` and
`Content-Security-Policy: default-src 'none'; sandbox`, with the access check of the
home first. Images are shown inline as photos are.

**Names.** The stored path is `<home>/<attachment>.<extension>`, identifiers only, in
`MEDIA_ROOT/attachments/`, a directory no address serves and with the permissions of the
photos. The name shown to people is the one sent, cleaned of folders, control and
direction characters (`clean_name`), limited to 120 characters, and always escaped by
the templates. The header of a download carries the identifier, never that name.

**Limits.** The size limit is the one of the photos (`HOUSECAIRN_PHOTO_MAX_BYTES`, 10 MB
by default); a request is refused before it is read when its declared size is over five
files' worth; 30 attachments per task. A voice note is not recorded in this version.

## Consequences

- A document of an accepted type may still be malicious for the program that opens it
  on the computer of the person who downloads it: it is stored and served as inert data,
  and not scanned.
- Deleting is soft, like every record (ADR 0005); files stay on disk until the purge of
  deleted records.
- Adding a type is a decision: its check goes in `files.detect` with its tests.
