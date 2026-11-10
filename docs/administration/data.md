# Export and deletion

The data of a home belongs to its owners, who can take it out and delete it;
the data of a person is erased with their account
([ADR 0023](../adr/0023-audit-log-export-erasure-and-email-alerts.md)). The
administrator of the instance does neither for a home they do not own.

## Export of a home

An owner downloads the archive from the page of the home (**Export all
data**) or from the API (`POST /api/v1/homes/<id>/export/`, signed in; an API
token cannot). The export is written to the audit log of the home
([ADR 0048](../adr/0048-export-format-and-restore.md)).

When the files of the home take more than 50 MB, the archive is made in the
background by the worker: the page of the export says when it is ready, and the
API answers `202` with the job (`GET /api/v1/homes/<id>/export/<job id>/`).
The archive is then downloaded by an owner, signed in, at most 3 times and
within 24 hours (`POST .../download/`, never a link that opens without
signing in). After that, the worker removes it within the hour, with any
partial archive left by an export the worker could not finish.

The archive is a zip:

| Part | Content |
| --- | --- |
| `manifest.json` | `format` (`"housecairn-export"`), `version` (`2`), `application_version`, `exported_at`, `home` (its id), `apps` (the documents below) and `entries`: the SHA-256 digest and the size of every other file of the archive. |
| `data/<app>.json` | The data of one part of the application: `{"app": ..., "sections": {<section>: [objects]}}`. |
| `files/<folder>/<id>.<extension>` | The files: `photos/`, `attachments/` (files of tasks), `stock/` (labels of stock items), `projects/` (photos, link pictures, quotes) and `reports/`. |
| `README.txt` | A reminder of the format. |

Its [JSON Schema](../_static/schemas/housecairn-export-v2.schema.json) is
published with this documentation. The rules that hold for every section:

- **Every field of the table**, by its name in the code: an object of
  `rooms` has `id`, `name`, `kind`, `position`, `notes`, `paint_colour`, ...,
  `created_at` and `updated_at`. A field added by a later version is in the
  archive without a change of format; a field removed or renamed raises the
  version.
- **Identifiers are the UUIDs** of the objects, never an internal number. A
  reference is the id of an object of the same archive, or `null`; a link to
  several objects (the rooms of a project) is a list of ids.
- **People** are named by an id of the `people` list of `data/homes.json`,
  which alone holds their e-mail address and display name; the restore uses
  the address to find their account.
- **Amounts and quantities** are text with a point (`"1250.50"`), never a
  number of JSON; amounts are in the currency of the home (`home.currency`).
  Dates are ISO 8601.
- **Files** are a path of the archive, or `null` when the file is missing on
  the disk. Photos are exported as stored, already stripped of their metadata
  at upload; documents as received. Thumbnails are not exported: a restore makes
  them again.
- **Only what is not deleted**, and nothing whose parent is: the history of a
  deleted task is not exported.

| Document | Sections |
| --- | --- |
| `homes` | `home` (id, name, currency, hemisphere, sign-in requirement, dates), `people`, `members` (person and role) and `pending_invitations` (address, role, dates; never the link). |
| `events` | `events` received, without the token they came with. |
| `rooms` | `rooms` (with the room memory), `items`, `photos`. |
| `stock` | `stock_items`, `stock_suppliers`, `stock_movements`. The quantity in stock is the sum of the movements. |
| `tasks` | `contractors`, `tasks`, `task_materials`, `occurrences` (the history: done, skipped, planned), `stock_draws`, `attachments`. |
| `projects` | `projects`, `project_budget_lines`, `project_quotes`, `project_files`, `project_links`, `project_tasks`, `project_envelopes`. What a line has committed is the sum of its accepted quotes. |
| `calendar` | `calendar_feeds`: that a feed exists and when; never its address or the digest of its secret. |
| `labels` | `labels`: the `code` an active QR label carries, so that the stickers still open the right page after a restore; `null` for a revoked one. |
| `reports` | `reports`, with their photo. |

The archive never holds a secret: no API token (not even its digest), no link
of an invitation or of a calendar feed, no address of a notification channel,
no password, no setting or single sign-on secret of the instance, nothing of
the first setup. Each app adds its tables to the registry of the export
(`homes.exports.register`); a test fails on a table that is in no section.

Version 1 archives (a single `export.json`, before this version) cannot be
restored: export the home again.

## Tables for a spreadsheet

Every member downloads a table of the home as CSV from the page of the home
(**Tables for a spreadsheet**), or from the API
(`GET /api/v1/homes/<id>/export/<table>.csv`, a token with the `read` scope
on the home included): `rooms`, `items`, `tasks`, `history`, `stock`,
`contractors`, `reports`. The file is UTF-8 with a byte order mark, which
Excel needs to read accents; the columns are the fields of the archive, people
are named by their display name and never by their address, amounts are numbers
with a point and the currency is a column of its own. A text that a spreadsheet
would run as a formula (starting with `=`, `+`, `-`, `@`, a tab or a carriage
return) is written after a `'`, so that it stays text.

Every CSV of HouseCairn, exported or imported, is separated by **commas**,
whatever the language.

## Opening a table in a spreadsheet

A spreadsheet that opens a CSV file by a double click guesses its separator,
its encoding and the type of each column from the settings of the computer. On
a French system it expects semicolons and puts every row in one column; it also
turns dates and identifiers into numbers. Open the file by the import of the
spreadsheet instead, and save it the same way before an import.

**Microsoft Excel, in French:**

1. In a new workbook, **Données › À partir d'un fichier texte/CSV** (*Data ›
   From Text/CSV*), then choose the file.
2. **Origine du fichier**: *65001 : Unicode (UTF-8)*; **Délimiteur**:
   *Virgule*; **Détection du type de données**: *Ne pas détecter les types de
   données*, so that dates stay `YYYY-MM-DD` and identifiers stay text.
   Then **Charger**.
3. To save it for an import: **Fichier › Enregistrer sous**, type **CSV UTF-8
   (délimité par des virgules)**. Excel writes the *list separator* of
   Windows, a semicolon on a French system, despite the name of the type: set
   it to a comma first (Windows settings, **Heure et langue › Région ›
   Paramètres régionaux supplémentaires › Séparateur de liste**), or save the
   file with LibreOffice. An import refuses a file separated by semicolons and
   says so.

**LibreOffice Calc:**

1. **Fichier › Ouvrir** (*File › Open*), then choose the file. In **Import de
   texte**: **Jeu de caractères** *Unicode (UTF-8)*, **Séparé par** *Virgule*
   only; select every column and give it the type *Texte* to keep dates and
   identifiers as they are.
2. To save it: **Fichier › Enregistrer sous**, type **Texte CSV (.csv)**,
   tick **Éditer les paramètres du filtre**, then **Utiliser le format Texte
   CSV**: **Jeu de caractères** *Unicode (UTF-8)*, **Séparateur de champ**
   `,`, **Séparateur de chaînes de caractères** `"`.

The `'` before a text that starts with `=`, `+`, `-` or `@` stays visible in
the cell; leave it there, the import takes it off.

## Import of tables

Owners and members add rows to a home from CSV files: on the page of the home,
**Tables for a spreadsheet › Import tables** ([the screen](../screens/home-import.md)),
or `POST /api/v1/homes/<id>/import/` (a token with the `write` scope on the
home included). The tables are those of the exports, with the same columns:
`rooms`, `items`, `tasks`, `stock` and `contractors`; a table exported, changed
in a spreadsheet and saved again comes back, one file per table, several tables
in one import.

- **Nothing is written before the confirmation.** The preview runs the import
  and rolls it back: it shows each row accepted or refused, with the reason,
  and is what the confirmation then writes, in **one transaction**, through
  the same checks as the forms. The API previews unless it is sent
  `confirm=true`.
- **Every file is checked whole first**: UTF-8 with or without a byte order
  mark, separated by commas, a header naming each known column once (by its
  name in the export, or its label in English or in French), and the column
  that names a row (`name`, or `title` for tasks).
- **Limits**: 1,000 rows and 2 MB for the files of one import; import a larger
  set in several times. Each row goes through the checks of the forms, twice
  (preview and confirmation): 1,000 rows keep each request within seconds, far
  from the 30 seconds after which the web server stops it. The preview sends
  the text of the files back with the confirmation, and Django refuses a form
  larger than 2.5 MB.
- **A row is always new.** It gets a new identifier; its `id` only lets the
  other files of the import refer to it. A row whose `id` is a row already in
  this home is refused as a duplicate, never merged; a name already used is
  accepted and flagged.
- **References stay in the home**: the `id` of a row of this home or of the
  same import, or the exact name of a row of this home. An identifier or a name
  of another home is refused. People are named by the display name of a member
  of the home; otherwise the row is left unassigned, and flagged.
- `created_at`, `updated_at`, the position of a room and the type of a stock
  label are made again by the import; a task is due on its `series_start`.
- The import is recorded in the audit log of the home, with the number of rows.

## Restore of a home

**Homes > Restore a home** (or `POST /api/v1/homes/restore/`, signed in; an
API token cannot) makes the archive a new home, owned by the person who
restores it. It does not become the current home. The identifiers are kept, so
that QR labels and links still lead to the same objects.

The archive is checked before anything is written, and refused with the
reason when it is not one HouseCairn made, or was changed since:

- only the names the format allows, no symbolic link, no encrypted file, no
  name that leaves the archive;
- a size, once unpacked, read from the zip before unpacking, no larger in all
  than the file quota of a home plus 64 MB (room for the data files); no file
  larger than the largest upload;
- a format and a version this instance knows, and every file present with the
  digest and the size its manifest gives;
- every value accepted by its field (a choice of the list, a valid date, a text
  no longer than allowed), every reference to an object the archive holds,
  never to an object of another home;
- no object already on this instance: the home it was made from must be
  deleted first, or the archive restored on another instance;
- every file decoded again, of the type its object says.

People are never given an account. From the web, the person restoring is
attached to what was theirs; the others are listed, left unattributed, and can
be invited again. For an instance that moves, the administrator runs:

```sh
docker compose exec housecairn python -m housecairn.entrypoint manage \
  restore_home /data/backups/housecairn-home.zip --owner owner@example.com
```

which attaches again every person of the archive who has an account here with
the same address, with their role.

A home that required a sign-in provider still requires it once restored. On an
instance that does not declare that provider, it stays locked, for its owner
too, until the rule is lifted: the owner opens the locked page and chooses
**Remove the sign-in requirement**, or the administrator uses **Remove these
requirements** on the instance page
([Requiring single sign-on for a home](oidc.md#requiring-single-sign-on-for-a-home)).

## Deletion of a home

An owner deletes the home from its page (**Delete this home**): type its exact
name. The home and everything in it go for good, for all its members: members,
invitations, events, calendar feeds, its audit log and its files; an API token left without a
home is revoked. **There is no grace period and no way back**: export first.
The audit log of the instance records that a home was deleted, without its
name.

The photos, the labels of stock items, the photos, link pictures and quote files of projects, the photos of reports and the files attached to tasks are erased from the disk with the home
(photos deleted one by one included). If the disk refuses (permissions, a full or
read-only volume), the home is still deleted and the error is logged by
`housecairn.files` with the path of the directory (`photos/<home id>`,
`attachments/<home id>`, `stock/<home id>`, `projects/<home id>`, `reports/<home id>` or `exports/<home id>`, the archives made in the background): remove that directory by hand.

The budget screens (by room, by project, by task, the envelope) keep no data of their own:
they are worked out from the projects, tasks and envelopes above, so they are in the export
and go with the home.

## Erasure of an account

**Delete my account** (see [Account pages](../screens/account.md)) erases the
account, its sign-in methods, devices, API tokens and calendar feeds, the homes where it is
the only member, and the invitations to its address. It is refused for the only
administrator and for the only owner of a home with other members: hand
ownership over, or delete the home, first. The audit log keeps that it happened
and no longer says who.

## Backups

Deleted data stays in backups until they expire: tell people how long you keep
them (see [Backup](backup.md)).
