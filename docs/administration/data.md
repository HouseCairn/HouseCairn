# Export and deletion

The data of a home belongs to its owners, who can take it out and delete it;
the data of a person is erased with their account
([ADR 0023](../adr/0023-audit-log-export-erasure-and-email-alerts.md)). The
administrator of the instance does neither for a home they do not own.

## Export of a home

An owner downloads the archive from the page of the home (**Export all
data**) or from the API (`POST /api/v1/homes/<id>/export/`, signed in; an API
token cannot). The export is written to the audit log of the home.

The archive is a zip:

| Part | Content |
| --- | --- |
| `export.json` | The data, as JSON (below). |
| `files/` | The files of the home, at the paths `export.json` lists: the photos, under `files/photos/`, the files of the tasks, under `files/attachments/`, the photos of the labels of stock items, under `files/stock/`, and the photos, the pictures of links and the quote files of projects, under `files/projects/`. |
| `README.txt` | A reminder of the format. |

`export.json` is versioned. Version `1` has these keys:

| Key | Content |
| --- | --- |
| `format`, `version` | `"housecairn-export"` and `1`. A change that removes or renames a key raises the version. |
| `exported_at`, `application_version` | When, and by which version. |
| `home` | `id`, `name`, `currency`, `hemisphere` (`north` or `south`), `required_provider`, `created_at`. |
| `members` | `id`, `email`, `name` (the display name, else the full name, else the part of the address before the `@`), `role`, `joined_at` of each member. |
| `pending_invitations` | `id`, `email`, `role`, `sent_at`, `expires_at`; never a link. |
| `events` | `id`, `kind`, `payload`, `received_at` of the events received. |
| `rooms` | `id`, `name`, `kind`, `position`, `notes`, `created_at` of each room, and its `memory` (paint colour, brand, reference, batch and stock, floor and wall covering, memory notes). |
| `items` | `id`, `room`, `name`, `kind`, `brand`, `model`, `serial_number`, `installed_on`, `warranty_ends_on`, `contract_provider`, `contract_number`, `contract_url`, `links`, `notes`, `created_at` of each item. |
| `photos` | `id`, `room` or `item`, `category`, `caption`, `content_type`, `size_bytes`, `width`, `height`, `created_at`, and `file`, the path of the photo in the archive (`files/photos/<id>.<extension>`, or `null` if the file is missing). |
| `attachments` | `id`, `task`, `occurrence` or `null`, `name`, `content_type`, `is_image`, `size_bytes`, `width`, `height`, `created_at`, and `file`, the path of the file in the archive (`files/attachments/<id>.<extension>`, or `null` if the file is missing). |
| `stock_items` | `id`, `name`, `manufacturer_reference`, `dimensions`, `storage_location`, `unit`, `threshold`, `quantity`, `compatible_items` (item ids), `notes`, `created_at`, and `label`, the path of the photo of the label in the archive (`files/stock/<id>.<extension>`, or `null`). |
| `stock_suppliers` | `id`, `article`, `name`, `reference`, `url`, `last_price`, `created_at`. |
| `stock_movements` | `id`, `article`, `kind`, `quantity`, `delta`, `occurred_on`, `note`, `created_at`. |
| `projects` | `id`, `title`, `goal`, `status`, `priority`, `rooms` (room ids), `estimated_minutes`, `season` with `season_start_month` and `season_end_month`, `created_at`. |
| `project_budget_lines` | `id`, `project`, `label`, `nature`, `planned`, `committed` (the sum of the accepted quotes), `paid`, `created_at`. Amounts are text with two decimals, in the currency of the home. |
| `project_quotes` | `id`, `project`, `contractor` (an id or `null`), `amount`, `issued_on`, `valid_until`, `status`, `budget_line` (the line an accepted quote is committed on, else `null`), `note`, `paperless_id`, `paperless_url`, `created_at`. |
| `project_files` | `id`, `project`, `quote` (or `null` for a photo of the project), `name`, `content_type`, `is_image`, `size_bytes`, `width`, `height`, `created_at`, and `file`, the path in the archive (`files/projects/<id>.<extension>`, or `null` if the file is missing). |
| `project_links` | `id`, `project`, `url`, `title`, `image` (the id of the picture in `project_files`, or `null`), `created_at`. |
| `project_tasks` | `id`, `project`, `task`: the tasks that belong to a project. |
| `project_envelopes` | `id`, `year`, `amount`: the annual budget envelope. |
| `tasks` | `id`, `title`, `room`, `item`, `priority`, `estimated_minutes`, the budgets, `notes`, `procedure`, `assignee`, `contractor` (an id), the repeat rule, `season` (`spring`, `summer`, `autumn`, `winter`, `heating`, `custom` or empty) with `season_start_month` and `season_end_month`, `hide_days_before`. |
| `contractors` | `id`, `name`, `trade` (a code of the list, or `other`), `trade_other`, `phone`, `email`, `address`, `note`. |
| `labels` | `id`, `kind` (`room`, `item` or `article`), `target` (the id of the room, item or stock item), `code`, `revoked_at`, `created_at` of each QR label. The `code` is the opaque identifier its sticker carries: it is exported for an active label and is `null` for a revoked one, which opens nothing. |
| `files` | `path` and `size` of each file in `files/`. |

Photos and the images attached to tasks are exported as they are stored, already
stripped of their metadata at upload; the documents attached to tasks are exported
as they were received. Thumbnails are not exported, and neither is anything
deleted. The archive has no size limit of its own: it is as large as the files of
the home (each is limited by `HOUSECAIRN_PHOTO_MAX_BYTES`).

Each lot that adds data adds its section here and to the archive. The archive
holds the home it was made for and nothing of another.

## Deletion of a home

An owner deletes the home from its page (**Delete this home**): type its exact
name. The home and everything in it go for good, for all its members: members,
invitations, events, its audit log and its files; an API token left without a
home is revoked. **There is no grace period and no way back**: export first.
The audit log of the instance records that a home was deleted, without its
name.

The photos, the labels of stock items, the photos, link pictures and quote files of projects and the files attached to tasks are erased from the disk with the home
(photos deleted one by one included). If the disk refuses (permissions, a full or
read-only volume), the home is still deleted and the error is logged by
`housecairn.files` with the path of the directory (`photos/<home id>`,
`attachments/<home id>`, `stock/<home id>` or `projects/<home id>`): remove that directory by hand.

## Erasure of an account

**Delete my account** (see [Account pages](../screens/account.md)) erases the
account, its sign-in methods, devices and API tokens, the homes where it is
the only member, and the invitations to its address. It is refused for the only
administrator and for the only owner of a home with other members: hand
ownership over, or delete the home, first. The audit log keeps that it happened
and no longer says who.

## Backups

Deleted data stays in backups until they expire: tell people how long you keep
them (see [Backup](backup.md)).
