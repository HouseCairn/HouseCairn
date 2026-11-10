# 0048. Export format 2, restore of a home, tables as CSV and backup of the instance

- Status: accepted
- Date: 2026-11-10

## Context

Each app exported its own section of `export.json` (format 1,
[ADR 0023](0023-audit-log-export-erasure-and-email-alerts.md)), written by hand. That
archive was for reading: nothing could put it back, its sections left fields out (the
start of a series, what an occurrence followed, who closed a report) and named people by
their address. The maintainer's own home is about to live on an instance for real (J4):
an owner must be able to move a home to another instance and get back every row and
every file, and an administrator must be able to back up and restore the instance as a
whole. Restoring is also the most dangerous input of the application: an archive is a
file anybody can forge.

## Decision

**Format 2: a manifest, one document per app, the files.** `manifest.json` gives the
format, its version, the version of the application, the date, the home, the list of
documents and the SHA-256 digest and size of every other entry. `data/<app>.json` holds
the sections of one app; `files/<folder>/<id>.<extension>` the files. The JSON Schema is
generated from the registry (`manage.py export_schema`) and published with the
documentation; a test fails when the published file and the code disagree, or when a
full archive does not validate. Format 1 is no longer written, and is not restored: its
archives carried neither digests nor every field.

**A registry of tables, no list of fields.** Each app registers its tables as `Section`s
in its `ready()`. The export writes **every concrete field** of each live row, by its name
in the code; a section only says what to leave out (a secret, a link to what is not
exported), which file fields carry a file, and, rarely, a hook (the code of a revoked QR
label). So a field added later is exported and restored without touching the export, and
a later lot adds a table with one call. Two tests hold it: every table of the project is
in a section, in the list of what the archive leaves out on purpose, or not data of a home
(ADR 0023); and every key of a section leads to the home, to a person or to another
section, every file field has its specification.

**Closed under its references.** A row whose required parent is not exported (the history
of a deleted task) is left out, until nothing changes; an optional reference to a row not
exported is written `null`. The archive never names an object it does not hold.

**Identifiers kept, people by reference.** Rows keep their UUIDs, so that QR labels, links
and integrations still point at the same objects after a restore. A person is an id of the
`people` list of `data/homes.json`, the only place with addresses and display names.

**Restore as a new home, in four checks before any write.** The zip (names on an
allow-list, no link, no encryption, no duplicate, sizes read from the headers and capped
before anything is unpacked, each entry read no further than its header says), the
manifest (known format and version, every entry listed with the right digest and size,
and nothing unlisted), the objects (each field parsed by its type and run through the
validators and choices of its model; each reference to an object of the same archive;
no identifier already used on the instance), the files (decoded again, of the type their
row says, within the upload limit and the quota of the home). The digests detect damage
and casual edits, not a forger, who can recompute them: the reference and identifier
checks are what keep an archive from reaching into another home. Then one transaction
writes the home, its rows (timestamps kept), its links and its files; a file already
written is removed if anything fails. Files are kept byte for byte, so a restore gives
back the same files; thumbnails are made again. A conflict on the same instance is refused
with the reason: delete the original home first, or restore elsewhere.

**Nobody gets an account.** From the web (and the API, signed in only), the person who
restores owns the new home and is attached to what was theirs; every other person is left
unattributed and named in the result, to be invited again. Matching every person of the
archive to an existing account by address would let anyone attach a stranger to a home,
and learn which addresses have an account here. `manage.py restore_home --owner`, run by
the administrator of the instance who moves homes, does match every person by address,
with their role. The restored home does not become the current home.

**Large homes in the background.** Above 50 MB of files, the export is an `ExportJob`: the
worker writes the archive under `MEDIA_ROOT/exports/<home id>/` (erased with the home, not
counted in its quota), and an owner, signed in, downloads it by a POST at most 3 times
within 24 hours; then an hourly schedule of the worker removes it, with any partial
archive older than that. No link opens without signing in.

**Tables as CSV, for a spreadsheet.** The rooms, items, tasks, history, stock,
contractors and reports, one table per file, from the same sections: UTF-8 with a byte
order mark, people by display name, amounts with a point and the currency in a column.
A text that starts with `=`, `+`, `-`, `@`, a tab or a carriage return is written after a
`'` (OWASP's advice on CSV injection); numbers are left alone. Any member, and a token
with the `read` scope on the home, may download them; the archive stays an owner's,
signed in.

**Backup of the instance in one file.** `manage.py backup_instance` writes a tar of a
consistent copy of the database (SQLite's online backup API, or `pg_dump` in its custom
format), the uploaded files and the secret key, with a manifest of digests, mode 600.
`restore_instance` checks every part first, refuses links and names that leave their
directory, keeps what it replaces aside (`<name>.before-restore-<date>`), and can restore
elsewhere to check a backup.

## Consequences

- The archive of a home can be read by a person and restored by a machine; its sections
  follow the models, so a migration that renames a field changes the format and raises its
  version.
- A restore on the instance the home came from is refused while that home exists.
- Archives of format 1 cannot be restored.
- The import of CSV files, the library of task templates (ADR 0049) and the guide of the
  API are a second pull request of the same lot.

## Options not taken

- **Django's `dumpdata` and `loaddata`.** They carry every table of the instance, internal
  ids of content types, and no check: `loaddata` writes what the file says, in any home.
- **A format per app written by hand**, as in format 1, with a restorer per section: every
  field would have to be listed twice, and forgetting one loses data silently.
- **Signing the archive.** The key would have to leave the instance to restore elsewhere;
  the checks above do not depend on who made the archive.
- **Matching every person by address from the web**: it leaks which addresses have an
  account and attaches people who did not agree to it.
