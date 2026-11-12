# 0069. Restore as a copy, with new identifiers

- Status: accepted
- Date: 2026-11-12
- Extends: [0048](0048-export-format-and-restore.md) (export format and restore of a home)

## Context

The restore of [0048](0048-export-format-and-restore.md) keeps every identifier of the
archive, so that the QR labels already stuck on the walls and the links still open the
restored objects. It is therefore refused while the home the archive was made from is on
the instance. A test of an instance by someone outside the project ran into it: there was no
way to duplicate a home (a second flat from the first one, a test home from a real one), nor
to check that a backup restores without deleting the original.

## Decision

- **A second way to restore: as a copy.** The restore page offers **Restore** and **Restore
  as a copy**; the API takes `as_copy` (and `name`) on `POST /api/v1/homes/restore/`, and
  `manage.py restore_home` takes `--copy` (and `--name`). Archives of format 2 and 3 are both
  accepted, as by the restore. There is no preview: the restore has none either.
- **The same path as the restore.** The copy is not a second reader of archives: the zip, the
  manifest, every value and every reference are checked by the very functions of the restore,
  on the identifiers of the archive, and every file is decoded again and stored as at upload.
  Then everything is written in one transaction; a failure, a refused file included, writes
  nothing and removes the files already stored.
- **The rule of new identifiers.** Once the archive is checked, each object of a restored
  table receives a new random identifier (UUID 4), drawn once per object and per model. Every
  key and every many-to-many link to an object of the archive takes the new identifier of
  that object, so that the copy names nothing of the original. The home gets a new identifier
  too. A value that is unique on the instance besides the identifier is drawn again by the
  `on_copy` hook of its section: today, the code of a QR label, so that the stickers of the
  original keep opening the original; a test fails for a unique column of a restored table
  that has no such hook. A one-to-one key is a key like the others and follows its target.
- **Files are copied, not shared.** A file is stored under the new identifiers of its home and
  of its row, its thumbnail made again; deleting the copy leaves the files of the original.
- **What is kept.** Every value that is not an identifier: names, notes, dates of the history
  (done on, cost), amounts, the links of inspiration, the reference of a Paperless document
  (it names a document of Paperless, which the copy may share). The rows keep their dates of
  creation; the home itself is created at the time of the copy.
- **People.** The person who copies owns the copy and is its only member: the members and the
  pending invitations of the archive are not copied, and the page says so. Only that person is
  matched among the people of the archive, from the command too; any other reference to a
  person is left empty, as from the web.
- **Name.** By default the name of the home followed by "(copy)", then "(copy 2)" and so on
  when the person already has a home of that name, shortened to fit; another name may be
  given, and changed later as any name.
- **Who may copy.** While the home of the archive is on the instance, only one of its owners
  may copy it (403 from the web page and the API, an error from the command): a member or a
  reader who was handed the archive must not turn the home into one they own, out of reach of
  its owners. Once that home is gone, the archive is all that is left, and whoever holds it may
  restore it or copy it, as before.
- **Audit.** The copy is recorded as `home.copied` in the log of the new home, with the format
  of the archive; nothing is written in the log of the original.

## Consequences

- A home can be duplicated, and a backup checked, on the instance where the home still is.
- A section that adds a unique column must say how a copy draws it again, or the test of the
  rule fails.
- The restore also gained from it: a file refused after others were stored no longer leaves
  those files on the disk.
