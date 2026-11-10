# Home

The page of one home, at `/h/<home id>/`: its name, your role in it, its
currency and its hemisphere. Its address stays the same as long as the home exists. The tabs above
the page switch between **Home settings**, **Household and roles** (its members) and,
for owners, the **Home audit log**; they are the same on those three pages.

When the home requires signing in through a provider and your session did not,
the page asks you to continue with that provider instead.

## Name, currency and hemisphere

Owners and members open **Name, currency and hemisphere** (`/h/<home id>/edit/`) to change
them. The hemisphere, **Northern** by default, decides what spring, summer, autumn, winter
and the heating season mean for the [tasks](task-form.md): it is never guessed from a place.
Changing it moves the window of the tasks that use a predefined season. Read-only members
do not see the row.

Under **Settings**, two rows lead to the [QR labels](qr-labels.md) and to the
[reports](reports.md) of the home; the second shows how many reports wait when you
may write.

## Tables for a spreadsheet

Every member sees the list **Tables for a spreadsheet**: the rooms, items,
tasks, history of the tasks, stock, contractors and reports, each as a CSV file
to open in a spreadsheet (see [Export and deletion](../administration/data.md)).

## Your data

Owners see two more actions at the bottom of the page.

- **Export all data** downloads one archive with everything of the home, in an
  open format (see [Export and deletion](../administration/data.md)). The
  export is recorded in the [audit log](audit.md). For a home with many files,
  the archive is made in the background: a page says when it is ready and
  offers **Download the archive**, at most three times within a day.
- **Delete this home** removes the home and everything in it, for good, for
  every member. The page asks you to type the exact name of the home, and
  offers the export first. There is no way back.
