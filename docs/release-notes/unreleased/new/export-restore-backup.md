---
orphan: true
nosearch: true
---

- **Restore a home.** **Homes > Restore a home** makes the archive of **Export all data**
  a new home, on this instance or another, with every room, task, history, stock item,
  project and file, under the same identifiers. A changed, foreign or unsafe archive is
  refused with the reason, and nothing is written
  ([Export and deletion](../../../administration/data.md)).
- **Tables for a spreadsheet.** Every member downloads the rooms, items, tasks, history,
  stock, contractors and reports of a home as CSV files that Excel opens with their
  accents, and that cannot run a formula.
- **Large homes are exported in the background**, then downloaded from the page of the
  export, at most three times within a day.
- **Back up the whole instance in one command**, `backup_instance`, and restore it with
  `restore_instance`, which checks every part first
  ([Data and backups](../../../administration/backup.md)).
