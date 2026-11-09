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
  screen to create a token yet. An API token is tied to homes: it can read the routes under
  `/api/v1/me/` where it could, but it cannot change the account, the display
  preferences or the notification channels and reminders of the person. Those are for the
  person signed in, and a token gets a 403 there:
  - `PATCH /api/v1/me/` (the display name);
  - `PATCH /api/v1/me/display-preferences/`;
  - `POST`, `PATCH` and `DELETE` on `/api/v1/me/notification-channels/` and
    `POST .../<id>/test/` (a test sends a message);
  - `PATCH /api/v1/me/notification-preferences/`;
  - `POST /api/v1/account/delete/`.

  `GET /api/v1/me/`, `me/home/` and `me/display-preferences/` stay open to a token;
  the `GET` routes of notifications need the `write` scope
  ([ADR 0045](../adr/0045-generic-lists-with-other-tabs-and-audit-of-content.md)).
- **Rooms, items and photos** of a home: `/api/v1/homes/<home id>/rooms/`,
  `.../items/`, `.../photos/` and `.../search/?q=`, with the same rules as the
  screens ([ADR 0029](../adr/0029-rooms-items-and-room-memory.md),
  [ADR 0030](../adr/0030-photo-storage-and-processing.md)). A token needs the
  `read` scope to read them and `write` to change them, and its user needs a role
  that writes. Rooms and items can be filtered with `q` (name); items with
  `room`; photos with `room`, `item` and `category` (`general`, `behind_walls`, `before`,
  `after` or `other`, [ADR 0045](../adr/0045-generic-lists-with-other-tabs-and-audit-of-content.md)).
  An item carries `contract_provider` and `contract_number`.
- **Tasks** of a home: `/api/v1/homes/<home id>/tasks/`, `.../occurrences/`,
  `.../contractors/` (name, `trade` from a list or `other` with `trade_other`, `phone`,
  `email`, `address`, `note`; `GET .../contractors/<id>/vcard/` gives the contact file) and
  `.../attachments/`
  ([ADR 0031](../adr/0031-tasks-occurrences-and-recurrence.md),
  [ADR 0033](../adr/0033-done-with-undo.md),
  [ADR 0034](../adr/0034-task-attachments.md)). Only `title` is required to create
  a task; `due_on` is the date of its open occurrence. `season` is `spring`, `summer`,
  `autumn`, `winter`, `heating` (the months follow the `hemisphere` of the home), `custom`
  (with `season_start_month` and `season_end_month`) or empty;
  `estimated_minutes` is in minutes, from 1 to 43200, and `estimated_text` reads it;
  `assignee_name` names the person in charge
  ([ADR 0045](../adr/0045-generic-lists-with-other-tabs-and-audit-of-content.md)). Everything the screens do
  is there: `POST .../occurrences/<id>/complete/` marks it done and creates the next
  occurrence (the response holds both), `.../undo/` takes it back, `.../skip/` and
  `.../postpone/` (body `{"due_on": "YYYY-MM-DD"}`) the other outcomes, and `PATCH`
  fills in the date, real cost and note of what was done. Tasks are filtered with
  `status` (`open`, `closed`), `room`, `item`, `assignee`, `due_before`, `due_after`
  `contractor` and `q`; occurrences with the same, plus `task`, `overdue=true` and `status`
  (`planned`, `postponed`, `done`, `skipped`, `open`, `closed`). Occurrences come
  oldest date first, the arrears on top, and the open ones hidden by their task
  (masked until N days before) only appear with `include_hidden=1`. The scopes are
  the same as for rooms: `read` to read, `write` to change, and a role that writes.
- **Me**: `GET` and `PATCH /api/v1/me/` read and change the `display_name` of the person
  signed in (`email` and `id` are read only); `name` is the name shown for them.
- **Today, My home, History and display preferences**
  ([ADR 0037](../adr/0037-today-my-home-history-and-display-preferences.md)):
  `GET /api/v1/homes/<home id>/today/` returns the sections of the Today screen as the
  display preferences of the caller lay them out; `GET /api/v1/me/home/` (with an optional
  `home`) what concerns the caller in each home; `GET` and `PATCH
  /api/v1/me/display-preferences/` the layout (`today_group`, `horizon_days`,
  `show_overdue`, `show_upcoming`, `show_season`, `language`), which only its owner can
  read or change (a token reads, the person signed in changes). `language` is a language the instance ships (`en`, `fr`) or empty to
  follow the browser; the web screens apply it from the next page. History is the occurrence list with `status=closed&ordering=recent` and the
  filters `contractor`, `completed_by`, `q`, `closed_after` and `closed_before`;
  `GET .../occurrences/cost/` gives the real cost entered on the same selection.
- **Stock** of a home: `/api/v1/homes/<home id>/articles/`, `.../suppliers/` and
  `.../movements/` ([ADR 0038](../adr/0038-stock-suppliers-and-movements.md)). Only
  `name` is required to create an article; its `quantity` is read-only, the sum of its
  movements, and `low` tells whether it is at or below its `threshold`. A movement is
  created with `POST` (`kind` is `entry`, `exit` or `inventory`, with a `quantity`) and
  never changed or deleted. `compatible_items` takes item identifiers of the same home;
  `label` (multipart) sets the photo of the label and `GET .../articles/<id>/label/`
  returns it. Articles are filtered with `q` (name, manufacturer reference or supplier)
  and `low=true`; suppliers and movements with `article`, movements also with `kind`. The
  scopes are the same as for rooms.
- **Projects** of a home ([ADR 0050](../adr/0050-projects-quotes-and-budget-lines.md)):
  `/api/v1/homes/<home id>/projects/`, `.../budget-lines/`, `.../quotes/`,
  `.../project-files/`, `.../project-tasks/` and `.../envelope/`. Only `title` is required
  to create a project; `budget`, on creation only, becomes its first budget line. Every
  amount is a string with two decimals in the currency of the home (`"1250.50"`), from
  `"0.00"` to `"9999999999.99"`; a JSON number (a float or an integer), a negative amount or a
  third decimal is a 400.
  A project and a budget line give `planned`, `committed` (the sum of the quotes accepted
  on it, read-only), `paid`, `gap` and `budget_state` (`over`, `under` or `on`).
  `POST .../quotes/<id>/accept/` with a `budget_line` of the same project accepts a quote
  and commits its amount on that line; a quote takes `contractor` (an id) or
  `contractor_name` (found or created). `project-tasks` takes a `title` (a new task is made
  in the project, with optional `due_on` and `room`) or a `task` (an existing one that is
  in no project); deleting a row takes the task out and keeps it. `project-files` takes
  `file` (multipart), with `quote` for the file of a quote, and `GET .../content/` and
  `.../thumbnail/` return the file. `GET` and `PUT .../envelope/` read and set the budget
  envelope of a `year`. Projects are filtered with `status`, `priority`, `season` and
  `room`, the other lists with `project`. The scopes are the same as for rooms.
- **Budget** ([ADR 0051](../adr/0051-budget-views-and-annual-envelope.md)), figures only,
  read-only (`GET`, the `read` scope): `/api/v1/homes/<home id>/budget/` (the envelope of a
  year, then `by_nature`, `by_year` and the last 12 months as `rolling`),
  `.../budget/rooms/`, `.../budget/projects/` and `.../budget/tasks/`, and `/api/v1/budget/`
  for all your homes added up by currency, with no conversion. `?year=` picks the year (this
  year by default; a year that is not one is a 400) and `?export=csv` answers with the same
  figures as a file. Every amount is a string with two decimals; a row gives `planned`,
  `committed`, `paid`, `engaged` (shown as *Used*: the more of committed and paid, line by
  line), `gap` (negative when exceeded), `to_pay` and `budget_state`. `sure_budget` of the
  envelope is always `null`. A home that is not yours, or that your token is not bound to, is
  a 404.
- **Notifications** of the caller
  ([ADR 0043](../adr/0043-notifications-through-apprise.md)):
  `/api/v1/me/notification-channels/` lists, adds (`name` and `url`, an Apprise address),
  renames or turns off (`PATCH` of `name`, `enabled`; any other field, `url` included, is
  a 400) and deletes the caller's channels; `url` is write-only and never returned.
  `POST .../<id>/test/` sends a real test message and answers
  `{"ok": true|false, "detail": ...}` with a fixed sentence. `GET` and `PATCH
  /api/v1/me/notification-preferences/` the reminders (`days_before`, `send_at`,
  `quiet_start`, `quiet_end`, `digest`, `language`, `time_zone`), and `GET
  /api/v1/me/notifications-export/` both, without any address. A token with the `write`
  scope reads them (any other token gets a 403); adding, renaming, deleting and testing a
  channel and changing the reminders are for the person signed in, and a token gets a 403
  there. Someone else's channel is a 404.

The [reference](reference.md) lists every operation. It is generated from the
OpenAPI 3.1 schema of the code at each build of this site:
{download}`download the schema (openapi.json) </_generated/openapi.json>`.
A running instance serves the same schema at `/api/schema/` and an
interactive explorer at `/api/docs/`, both to signed-in users only.

```{toctree}
:maxdepth: 1

reference
```
