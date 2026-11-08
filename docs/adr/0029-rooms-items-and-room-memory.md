# 0029. Rooms, items and room memory

- Status: accepted
- Date: 2026-11-08

## Context

A home is described room by room: what is in each room, what was used and fitted
there, and what has to be maintained. Tasks and the maintenance log (a later lot)
hang off these records, and QR labels will open them, so their identity and
their addresses must be settled before anything refers to them.

## Decision

**Models** (app `rooms`, every one a `HomeOwnedModel`: UUID, timestamps, soft
deletion, a home, ADR 0005 and 0006):

- `Room`: name (the only required field), type (a short list, "other" by
  default), position, notes, and the **room memory** as plain optional fields:
  paint (colour, brand, reference, batch, what is left in stock), floor and wall
  coverings, free notes. The memory is columns rather than a free JSON document
  so that it is limited, validated and searchable later; paint is one set per
  room, not a list, for the first version.
- `Item`: a piece of equipment or a surface in a room: name, brand, model,
  serial number, installation date, end of warranty, maintenance contract (text
  and an `http(s)` link), up to ten labelled links, notes. Moving an item is
  changing its room; the service refuses a room of another home.
- `Photo`: see ADR 0030.

**Order.** Rooms have a `position`; `reorder_rooms` renumbers the home's rooms
in one transaction, with the listed rooms first. The web offers up and down
buttons (no script needed), the API a `reorder` action. Cursor pagination of the
room list follows the position, not the creation time.

**Deletion.** Deleting a room soft-deletes its items and photos in the same
transaction; deleting an item soft-deletes its photos.

**Addresses** (ADR 0010): `/h/<home>/rooms/<uuid>/`, `/h/<home>/items/<uuid>/`,
`/h/<home>/photos/<uuid>/`, and the same under `/api/v1/homes/<home>/`. A
record that does not exist and a record of another home answer the same 404.
The entry `/rooms/` of the navigation leads to the rooms of the user's home, or
asks which one.

**Roles** are those of ADR 0020: owners and members write, read-only members
read. Checked in `rooms.services`, so the web and the API cannot differ. The
instance administrator has no access without being a member (ADR 0006): these
models are not registered in Django's administration site.

**Search** is a case-insensitive "contains" on the name, in the services,
limited to 50 results per kind and to the home.

**Placeholders.** The item page has the place of the maintenance log and cost
of ownership; nothing is shown until the tasks lot creates entries.

## Consequences

- Photos, tasks and documents refer to a room or an item by UUID; renaming or
  moving never breaks a link.
- A purge policy for soft-deleted rows is still to be decided with the export and
  deletion lot (ADR 0005).
- A second paint, or a list of coverings, needs a new model; the memory fields
  are deliberately few.
- Links are validated as `http` or `https` and shown with
  `rel="noopener noreferrer nofollow"`: a stored `javascript:` address cannot be
  rendered as a link.
