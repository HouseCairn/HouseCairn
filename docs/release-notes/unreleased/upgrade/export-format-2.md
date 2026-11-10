---
orphan: true
nosearch: true
---

- **The archive of a home changes format.** **Export all data** now gives format 2: a
  `manifest.json` with the digest of every file, one `data/<app>.json` per part of the
  application with every field of each table, and the files; its JSON Schema is published
  with the documentation. A script that read `export.json` must read the new documents.
  Archives of format 1 cannot be restored: export the homes again after the update
  ([Export and deletion](../../../administration/data.md)).
