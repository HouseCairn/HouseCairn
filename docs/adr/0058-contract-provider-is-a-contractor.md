# 0058. The provider of a maintenance contract is a contractor, and export format 3

- Status: accepted
- Date: 2026-11-11
- Amends: [0048](0048-export-format-and-restore.md) (export format 2 becomes 3)
- Extends: [0045](0045-generic-lists-with-other-tabs-and-audit-of-content.md) (contractors)

## Context

The provider of the maintenance contract of an item was a free text
(`Item.contract_provider`) with no link to the contractors of the home. The same company
was typed twice, once in the contract and once as the contractor of a task, and a task made
from an item guessed the contractor by comparing names. The maintainer decided on
2026-11-11 that the provider is a choice in the list of the contractors of the home, with
**Add a contractor…** to create one in place, as the task form does.

## Decision

- **A link, not a text.** `Item.contract_contractor` is an optional foreign key to
  `tasks.Contractor`, `on_delete=SET_NULL`, `related_name="maintained_items"`. The text field
  is removed. The model refuses a contractor of another home or a deleted one (`Item.clean`, run
  by every service, so by the web, the API and the imports alike); the form and the API
  serializer also offer only the contractors of their home, so that the choice is not even
  shown.
- **Deleting a contractor clears the link.** `tasks.services.delete_contractor` clears it on
  the items, deleted ones included, as it does on the tasks (a soft delete does not trigger
  `SET_NULL`). The number and the link of the contract stay: they are the contract; the
  provider was only its address book entry. The alternative, keeping a deleted contractor
  readable, would show a name that the list of contractors no longer holds.
- **One mechanism to add in place.** The field is a `tasks.forms.fields.AddInPlaceChoiceField`
  and the fields of the new contractor are those of the task form
  (`tasks.forms.contractor.new_contractor_fields`, `clean_new_contractor`). The view creates
  the contractor and the item in one transaction.
- **The data migration** (`rooms.0005`, reversible) links, for each item with a provider
  text, the contractor of its home of that name (case and extra spaces ignored; the oldest
  if two share it). When there is none, it creates one with the trade `other`, said as
  `Maintenance` (the trade Other needs a word, and this one reads the same in English and in
  French), shared by the items of that home that name the same provider; a text longer than
  a name goes whole into the note. Going back writes the name of the contractor into the text;
  the contractors that the migration made stay, because an item added since may use them.
- **Export format 3.** A field removed raises the version (ADR 0048): `contract_provider`
  leaves `rooms.items` and `contract_contractor` (an id of `tasks.contractors`, or `null`)
  comes in. The JSON Schema is published as `housecairn-export-v3.schema.json`; the version 2
  schema stays published, as version 2 archives are still restored.
- **A version 2 archive is restored** (`SUPPORTED_VERSIONS = {2, 3}`). Before its objects are
  checked like any other, `homes.restore._upgrade_v2` rewrites it in memory by the rule of the
  migration, adding the contractors it needs to the `contractors` list of the archive. The
  checks of ADR 0048 do not change: the rewritten archive goes through all of them.
- **CSV.** The `items` table names the contractor by id. On import, the column accepts an id
  or a name (a name that is not a contractor of the home yet is created, by the rule above,
  in the transaction of the import, so that the preview writes nothing), and the old column
  `contract_provider` is read as such a name. The `contractors` table is imported before
  `items`, so a file can bring both.

## Consequences

- An instance updated from 0.1.0 gets contractors it did not have, one per distinct provider
  text that is not a contractor already. They show in the list of contractors; the upgrade
  notes say so.
- The API loses `contract_provider` on items. The project is before 1.0; the change is
  announced in the upgrade notes rather than kept as a second, read-only name.
- The Home Assistant integration does not read items: nothing changes for it. Only the
  OpenAPI fixture of its tests names `contract_provider`; it is updated in its own
  repository.
