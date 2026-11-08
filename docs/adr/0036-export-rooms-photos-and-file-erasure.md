# 0036. Export of rooms and photos, erasure of files with the home

- Status: accepted
- Date: 2026-11-08

## Context

The export of a home (ADR 0023) is a right of the person, and its deletion is for
good. Two gaps were found after the rooms lot (ADR 0029, 0030): the archive held
no room, item or photo, because that lot was merged before apps could register an
exporter; and deleting a home removed `MEDIA_ROOT/homes/<id>/` while photos are
stored in `MEDIA_ROOT/photos/<id>/`, so they stayed on the disk.

## Decision

**Export.** The rooms app registers three sections, from `RoomsConfig.ready`, like
the other apps: `rooms` (with the room memory as a `memory` object), `items`
(warranty and contract included) and `photos` (metadata and the archive path of
the file). The files of the photos go under `files/photos/<photo id>.<ext>`;
they were stripped of their metadata at upload (ADR 0030). Thumbnails are not
exported: they are made again. Soft-deleted records are not exported. A photo
whose file is missing, or whose stored name does not lead to a file directly
inside its own home's folder, is listed without a file (`"file": null`) and never
read. The format version stays 1: sections are added, none is changed.
The export has no size limit of its own, before or after this decision: the
archive is written to a temporary file, bounded by the photo limits of ADR 0030
(10 MB by default, 30 per room or item).

**Erasure.** Each app that stores files for a home keeps them in
`MEDIA_ROOT/<folder>/<home id>/` and declares the folder with
`homes.files.register_media_folder` (`photos` here; `attachments` for the files
of tasks). `erase_home` removes the directory of the home in every declared
folder, after the deletion of the rows is committed. The path is built from the
home UUID only, never from a name sent by a person. A directory that is a
symbolic link is removed as a link and not followed; a directory that does not
resolve to a direct child of its folder is refused; `shutil.rmtree` does not
follow links either.

**A failure to erase is logged, not raised.** The rows are already deleted and the
deletion is final for the person; turning it into an error would invite a second
attempt on a home that no longer exists, and nothing could retry it. The error is
logged (`housecairn.files`, the path of the directory, which holds the home UUID, no content) so that an
administrator can remove the directory by hand. The alternative, failing the
deletion when a file cannot be removed, leaves the person with a home they asked
to delete and files that may be half gone.

**Photos deleted one by one** are a different case: the record is soft-deleted
(ADR 0005) and its files stay until a purge of deleted records, which does not
exist yet and is not part of this decision. They are erased with the home.

## Consequences

- A later app that stores files declares its folder in its `ready`; forgetting to
  do so is the only way to leave files behind.
- A deletion that fails on the disk leaves orphan files, reported in the log.
- The purge of individually deleted photos remains to be decided with the purge
  of deleted records.
