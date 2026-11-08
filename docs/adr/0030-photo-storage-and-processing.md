# 0030. Photo storage and processing

- Status: accepted
- Date: 2026-11-08

## Context

Rooms and items carry photos, taken on a phone: the open wall before it is
closed, the label of a boiler. An uploaded file is untrusted input. A phone
photo carries the location of the house in its metadata, and the house is private
data of the household. The data volume already holds the database and the
backups (ADR 0015).

## Decision

**Pillow** decodes the images (runtime dependency, added to ADR 0001): there is
no safe way to check an image without decoding it, and writing JPEG, PNG and
WebP codecs is not an option.

**The type is decided by the content.** The upload is decoded with Pillow
restricted to JPEG, PNG and WebP (`Image.open(..., formats=...)`): the file name
and the `Content-Type` sent by the client are never read. A text, HTML or SVG
file renamed `.jpg`, a truncated image, any other format (GIF, BMP, TIFF, HEIC)
and an image of more than 40 megapixels are refused with a validation error.

**The image is written again.** After a full decode, the orientation is applied
to the pixels and the image is encoded from them in the same format (JPEG at
quality 85, PNG, WebP at quality 85), reduced to 2,560 pixels on its longest
side. Nothing of the original file survives: EXIF (location, camera, date), XMP,
comments and bytes appended or hidden in the file are gone. The colour profile
and, for a palette PNG, its transparent index are kept, so colours do not shift.
A 360-pixel JPEG thumbnail is made at the same time. Removing the whole
metadata, not only the GPS block, is simpler to state and to test, and the cost
is that the date of the photo is not kept either; the record's `created_at` is.

**Size.** A photo is limited by the environment variable
`HOUSECAIRN_PHOTO_MAX_BYTES` (default 10 MB, accepted from 10 KB to 100 MB,
checked by `manage.py check`). The check uses the declared size, then reads at
most one byte more than the limit, so a sender that declares nothing is limited
too. Before the body of a request is read, a `Content-Length` over the limit
plus 256 KB answers 413. A room or an item holds at most 30 photos. Quotas per
home arrive with the files lot. The variable is read by `rooms.conf`, not
declared in `settings.py`.

**Names.** The name sent with the file is dropped. Stored names are
`<home id>/<photo id>.<ext>` and `<home id>/<photo id>-thumb.jpg`, built from
UUIDs, under `MEDIA_ROOT/photos/` (`/data/media/photos/` in the image), with
modes 0640 and 0750. No URL serves that directory.

**Serving.** Only the views of the app send a photo, after the home check of
ADR 0006 (a photo of another home, or an unknown one, answers 404, for a member
of another home and for the instance administrator alike). The response carries
the type found at upload, `Content-Disposition: inline; filename="<photo
id>.<ext>"`, `X-Content-Type-Options: nosniff`, a policy `default-src 'none';
sandbox` and `Cache-Control: private`. The same files are served by the API
(`.../photos/<id>/content/` and `.../thumbnail/`) to tokens with the `read` scope.

**Deletion.** Deleting a photo is a soft deletion (ADR 0005): the record and
the files remain until the purge of deleted records, which is decided with the
export and deletion lot. If the database write fails after the files were
written, they are removed.

## Consequences

- The database and `/data/media/` are backed up together (the backup
  documentation already lists both).
- Encoding happens in the request, and a very large image takes noticeable time
  to decode and write again. A background task (ADR 0008) is the way out if
  that proves too slow.
- Uploads over 2.5 MB go through Django's temporary files, in the container's
  `/tmp` (a 64 MB tmpfs in the example deployment, ADR 0015): the default limit
  leaves room for several uploads at once.
- Pillow is a native, regularly patched dependency: it follows the dependency
  update policy of ADR 0014 like the others.
