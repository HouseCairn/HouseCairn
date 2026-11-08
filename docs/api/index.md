# API

HouseCairn has a REST API, mounted at `/api/v1/`, with the same rules as the
web interface: every request only sees the homes of its user
([ADR 0004](../adr/0004-versioned-rest-api.md),
[ADR 0006](../adr/0006-home-scoping.md)).

- **JSON** for requests and responses, except the upload of a photo or of a file
  of a task, which is `multipart/form-data` (`POST /api/v1/homes/<home id>/photos/`
  and `.../attachments/`), and the image, thumbnail or file themselves, which are
  served as they are.
- **Versioned**: version 1 only gets additive changes; a breaking change will
  go to `/api/v2/`, served alongside version 1 for a deprecation period.
- **Cursor pagination**, up to 200 items per page.
- **Updates** with `PATCH`; `PUT` is not offered.
- **Authentication** by API token, `Authorization: Bearer hc_...`, with the
  scopes `read`, `write` and `events`, bound to one or more homes and expiring
  after 90 days by default
  ([ADR 0007](../adr/0007-authentication-and-api-tokens.md)). There is no
  screen to create a token yet.
- **Rooms, items and photos** of a home: `/api/v1/homes/<home id>/rooms/`,
  `.../items/`, `.../photos/` and `.../search/?q=`, with the same rules as the
  screens ([ADR 0029](../adr/0029-rooms-items-and-room-memory.md),
  [ADR 0030](../adr/0030-photo-storage-and-processing.md)). A token needs the
  `read` scope to read them and `write` to change them, and its user needs a role
  that writes. Rooms and items can be filtered with `q` (name); items with
  `room`; photos with `room`, `item` and `category`.
- **Tasks** of a home: `/api/v1/homes/<home id>/tasks/`, `.../occurrences/`,
  `.../contractors/` and `.../attachments/`
  ([ADR 0031](../adr/0031-tasks-occurrences-and-recurrence.md),
  [ADR 0033](../adr/0033-done-with-undo.md),
  [ADR 0034](../adr/0034-task-attachments.md)). Only `title` is required to create
  a task; `due_on` is the date of its open occurrence. Everything the screens do
  is there: `POST .../occurrences/<id>/complete/` marks it done and creates the next
  occurrence (the response holds both), `.../undo/` takes it back, `.../skip/` and
  `.../postpone/` (body `{"due_on": "YYYY-MM-DD"}`) the other outcomes, and `PATCH`
  fills in the date, real cost and note of what was done. Tasks are filtered with
  `status` (`open`, `closed`), `room`, `item`, `assignee`, `due_before`, `due_after`
  and `q`; occurrences with the same, plus `task`, `overdue=true` and `status`
  (`planned`, `postponed`, `done`, `skipped`, `open`, `closed`). Occurrences come
  oldest date first, the arrears on top, and the open ones hidden by their task
  (masked until N days before) only appear with `include_hidden=1`. The scopes are
  the same as for rooms: `read` to read, `write` to change, and a role that writes.
- **Today, My home, History and display preferences**
  ([ADR 0037](../adr/0037-today-my-home-history-and-display-preferences.md)):
  `GET /api/v1/homes/<home id>/today/` returns the sections of the Today screen as the
  display preferences of the caller lay them out; `GET /api/v1/me/home/` (with an optional
  `home`) what concerns the caller in each home; `GET` and `PATCH
  /api/v1/me/display-preferences/` the layout (`today_group`, `horizon_days`,
  `show_overdue`, `show_upcoming`, `show_season`), which only its owner can read or
  change. History is the occurrence list with `status=closed&ordering=recent` and the
  filters `contractor`, `completed_by`, `q`, `closed_after` and `closed_before`;
  `GET .../occurrences/cost/` gives the real cost entered on the same selection.

The [reference](reference.md) lists every operation. It is generated from the
OpenAPI 3.1 schema of the code at each build of this site:
{download}`download the schema (openapi.json) </_generated/openapi.json>`.
A running instance serves the same schema at `/api/schema/` and an
interactive explorer at `/api/docs/`, both to signed-in users only.

```{toctree}
:maxdepth: 1

reference
```
