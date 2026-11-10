# Import tables

The page **Import tables** of a home, at `/h/<home id>/import/`, adds rows to the
home from CSV files: rooms, items, tasks, stock and contractors. Owners and members
open it from the page of the home, at the end of **Tables for a spreadsheet**;
read-only members do not see it. Its back link leads to the page of the home.

## The files

Give one file per table, as many tables as you like, in one go. A file has the
columns of the table the home exports under the same name (see
[Tables for a spreadsheet](../administration/data.md#tables-for-a-spreadsheet)):
export the table first, fill it in a spreadsheet, and import it. Only the column
that names a row is required, `name` (or `title` for tasks); a column the page
does not know is ignored, and listed.

- **Separated by commas**, always, like the exports.
- **UTF-8**, with or without a byte order mark.
- At most **1,000 rows** and **2 MB** for the files of one import, accents
  included; files past a limit are refused whole, with the reason.

A spreadsheet must keep the commas, the dates and the accents when it saves the file
again. In short, the steps of
[Opening a table in a spreadsheet](../administration/data.md#opening-a-table-in-a-spreadsheet):

- **Excel in French**: open the file by **Données › À partir d'un fichier texte/CSV**,
  with **Origine du fichier** *65001 : Unicode (UTF-8)*, **Délimiteur** *Virgule* and
  **Détection du type de données** *Ne pas détecter les types de données*. Save it as
  **CSV UTF-8 (délimité par des virgules)**, after setting the **list separator** of
  Windows to a comma: on a French Windows, Excel otherwise writes semicolons, which
  the import refuses.
- **LibreOffice Calc**: open the file with the character set *Unicode (UTF-8)* and
  the separator *Virgule* (comma); save it as **Texte CSV**, ticking **Éditer les
  paramètres du filtre**, with the field separator `,`.

## Preview, then confirm

**Preview** reads the files and checks every row, but writes nothing. The page then
shows, for each table, how many rows are accepted and refused, and each refused row
with its line and the reason: a value that is not valid, a room that is not in this
home, a row already in this home. A file that cannot be read at all (not UTF-8,
separated by semicolons, without the column that names a row, past the limits)
is refused whole, and nothing can be confirmed.

**All or nothing.** While a single row is refused, the page offers no **Import**
button and says so: correct the file, then choose it again. A warning (a name
already used, a person left unassigned) does not stop the import.

**Import** adds every row, all at once: if anything fails while writing, nothing is
added. The page then leads back to the page of the home, and the import is recorded
in the [audit log](audit.md). **Cancel** leaves without adding anything.

Between the two steps the files stay on the server, for you and this home only, for
**30 minutes**; the confirmation sends back only a signed token. After that, or once
used, the preview cannot be confirmed any more: the page says so and asks for the
files again.

## What a row becomes

- A row is always a **new** row, with a new identifier. A row whose `id` is a row
  already in this home is refused, never merged: importing the same file twice adds
  nothing the second time.
- A **reference** (the room of an item, the item of a task, its contractor) is the
  `id` of a row of this home or of the files imported with it, or the exact name of
  a row of this home. A reference to a row of another home is refused.
- A **person** (the assignee of a task) is the display name of a member of this home;
  when no single member has it, the task is left unassigned, and the page says so.
- A name already used in this home is accepted and flagged: two rooms may share a name.
- The `'` that the export puts before a text a spreadsheet would compute
  (`'=…`, `'+33 …`) is taken off again.
- The date of a task, `series_start`, is the date of its first occurrence. Dates are
  written `YYYY-MM-DD`.
- `created_at`, `updated_at`, the position of a room and the type of a stock label are
  made again; files (photos, labels) are not in the tables.

The API does the same:
`POST /api/v1/homes/<id>/import/` with the files as `rooms`, `items`, `tasks`,
`stock` and `contractors`, answers the preview (`confirmable` says whether it can be
written), and writes only with `confirm=true`, sending the files again; with a single
row refused it answers 400 with the reasons and writes nothing. A token needs the
`write` scope on this home.
