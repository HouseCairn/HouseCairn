---
orphan: true
nosearch: true
---

- **Import tables from CSV files.** Owners and members add rooms, items, tasks, stock and
  contractors to a home from the CSV files of **Tables for a spreadsheet**, edited in a
  spreadsheet: the preview shows each row accepted or refused with the reason and writes
  nothing, then **Import** adds every row in one go, all or nothing: while a single row is
  refused, nothing is imported. At most 1,000 rows and 2 MB per import. A row already in
  the home is refused, never merged, and a reference to another home is refused. The API does the
  same with `POST /api/v1/homes/<id>/import/` and a token with the `write` scope
  ([Import tables](../../../screens/home-import.md)).
- **Opening a table in Excel or LibreOffice** is explained step by step, French menus
  included: every CSV of HouseCairn stays separated by commas
  ([Export and deletion](../../../administration/data.md#opening-a-table-in-a-spreadsheet)).
