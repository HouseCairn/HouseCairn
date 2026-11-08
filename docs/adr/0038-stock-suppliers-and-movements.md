# 0038. Stock: items, suppliers and an append-only ledger of movements

- Status: accepted
- Date: 2026-11-08

## Context

A home keeps spare parts and supplies: filters, paint, batteries. The questions are
how many are left, where they are, what they fit and where to buy more. The rooms
app already holds the equipment (ADR 0029) and the processing of untrusted images
(ADR 0030); the export and the erasure of files are extensible (ADR 0036).

## Decision

**A new app, `stock`**, with three tables: `Article` (name, manufacturer reference,
dimensions, storage location, unit, threshold, notes, label photo, and a many-to-many
link to `rooms.Item`), `Supplier` (an article has several) and `Movement`. No file of
another app changed: the link to items is declared on the stock side, with no reverse
name, so the item page does not show it yet.

**The quantity has one source: the movements.** A movement is an entry, an exit or an
inventory. It is never updated or deleted by the services; a mistake is corrected by
a new line. `quantity` keeps what was typed; `delta`, computed once when the line is
written, is its effect on the stock (`+q`, `-q`, or the counted quantity minus the
stock at that moment for an inventory). The stock of an article is the sum of its
deltas, computed by a query and stored nowhere. An exit that would take the stock
below zero is refused. Each write locks the article row so that two concurrent
movements cannot both pass the check. Alternative rejected: a stored quantity updated
beside the ledger, which creates two truths that drift apart.

**The label photo goes through `rooms.images.process` as it is** (type by content,
size and dimension limits, metadata and location dropped), stored under
`MEDIA_ROOT/stock/<home id>/`, and served only by a view that checks the home,
inline, with the type found at upload, `nosniff` and a sandbox policy. The folder is
declared with `homes.files.register_media_folder` so that the erasure of the home
removes it.

**Purchase links** use the existing validated `http`/`https` field. They are rendered
as plain links with `rel="noopener noreferrer nofollow"`; the server never fetches
them and there is no preview.

**Isolation.** Every query goes through the home; compatible items, suppliers and
movements are checked against the home of the article on the web and in the API.
Owners and members write, read-only members read (ADR 0020).

**Export.** Three sections are registered (`stock_items`, `stock_suppliers`,
`stock_movements`) and the label photos go under `files/stock/`. Records of a deleted
item are not exported (ADR 0005).

## Out of scope

The deduction of stock when a task is done, the purchase forecast over 30, 60 and
90 days, and the QR labels belong to later lots.
