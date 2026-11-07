# 0005. UUID identifiers, timestamps, soft deletion

- Status: accepted
- Date: 2026-11-07

## Context

Records are referenced from outside the application: QR labels, universal
links, the iOS app's offline cache, Home Assistant automations. Sequential
integer identifiers leak volumes and can be guessed; an offline client needs
to know what changed and what was deleted since its last sync.

## Decision

Every model inherits `housecairn.core.models.BaseModel`:

- `id`: random UUID (version 4), primary key. There is no other identifier, so
  no internal one can leak;
- `created_at` (indexed) and `updated_at`;
- `deleted_at`: soft deletion. The default manager `objects` hides deleted
  rows; `all_objects` sees them. `soft_delete()` and `restore()` on instances,
  `soft_delete()` on querysets.

The user model also has a UUID primary key (0007).

## Consequences

- A deleted record stays in the database until a purge policy (to be decided
  with the export and backup lot) removes it, so a sync client can learn about
  deletions.
- Related-object access (`event.home`) uses Django's base manager and still
  reaches a soft-deleted parent; queries that list records must go through
  `objects`.
- UUID version 4 keys index less compactly than sequential keys; at the
  expected volumes (one household) this is negligible. UUID version 7 can be
  adopted later without a schema change.
