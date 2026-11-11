---
orphan: true
nosearch: true
---

- **The provider of the maintenance contract of an item is now a contractor.** The update
  changes the data of every home, once, and can be undone (`manage.py migrate rooms 0004`):
  for each item whose provider was a text, items in the trash included, the contractor of the
  same home with that name (case and extra spaces ignored) becomes its provider; when the home has none, a contractor
  of that name is created, with the trade **Other** said as **Maintenance** (change it on its
  sheet), and shared by the items that name the same provider. A text longer than 120
  characters, the length of a name, is cut for the name and kept whole in the note of the
  contractor. Going back puts the name of the contractor into the text again; the contractors
  made by the update stay. Nothing is asked and nothing is lost.
- **Export format 3.** The archive of a home and the table of items name the provider of a
  contract by the id of its contractor (`contract_contractor`) in place of the text
  (`contract_provider`), and the archive says version 3. A version 2 archive, and a table of
  items with the old column, are still restored and imported, by the rule above. API
  clients that read or write `contract_provider` on an item use `contract_contractor`, the id
  of a contractor of the home, instead
  ([export](../../../administration/data.md), [API](../../../api/index.md),
  [ADR 0058](../../../adr/0058-contract-provider-is-a-contractor.md)).
