# 0050. Projects, quotes and budget lines

- Status: accepted
- Date: 2026-11-09

## Context

A home also has work that is not a chore: redo the bathroom, paint the living room. It has
an end, several steps, quotes from contractors and a budget that is checked against what is
spent. The owner wants to say "redo the bathroom, 5000 euros", list the steps as tasks
inside it, and compare projects. Tasks (ADR 0031), contractors (ADR 0045), attachments
(ADR 0034), the quotas of files (ADR 0042) and the export of a home (ADR 0023, 0036) exist.
Other lots change `tasks`, `rooms` and `stock` at the same time, so this one adds an app
and changes none of them.

## Decision

**A new app, `projects`**, with `Project`, `BudgetLine`, `Quote`, `ProjectFile`,
`ProjectTask` and `AnnualEnvelope`, all owned by a home (ADR 0006) and soft-deleted
(ADR 0005). Only the title of a project is required. It has a status (idea, planned, in
progress, finished, abandoned), a priority, the rooms concerned, an estimated duration and
a preferred season. The duration is a number and a unit on screen and minutes in the data,
as for tasks, from a minute to a year (a task: thirty days). The season is one of the
seasons of tasks; a predefined one takes the months of the hemisphere of the home *when it
is read*, so a change of hemisphere needs no update of the projects.

**The link between a task and a project is held by `projects`.** `ProjectTask` has a
`OneToOneField` to `tasks.Task`: a task is in one project at most, the constraint is the
database's, and `tasks` has no field, no migration and no import of `projects`. A task of a
project is made by calling `tasks.services.create_task`, then the link is written in the
same transaction. The page of a task shows its project through one template tag of
`projects` (`task_project`). The link is removed with the task by the cascade of the foreign
key when the task is purged; a task that is only soft-deleted is hidden by the queries of
`projects` (they filter on `task__deleted_at`). Deleting a project keeps its tasks and drops
the links. Alternative rejected: a `project` field on `Task`, which would have merged with
the migrations of the lots changing tasks.

**A budget is lines, and an amount has three values.** A line has a label, a nature
(materials, labour, rental, other) and:

- `planned`, typed;
- `paid`, typed (a later lot checks it against the real payments in Sure);
- `committed`, **never stored**: the sum of the amounts of the quotes accepted on the line.

The *gap* of a line or of a project is `planned - max(committed, paid)`: what is promised
or already paid, whichever is more, set against the plan. It is negative when the budget is
exceeded. The screens say it in words ("Over budget by ...", "... left", "On budget") and
the table has headers; colour is never the only signal. A project's figures are the sums of
its lines. Because `committed` is derived, changing the amount of an accepted quote, or
deleting it, moves the commitment with no second write to keep in step. Alternative
rejected: a stored `committed` field, which would be a second truth to keep equal to the
quotes.

**Accepting a quote commits it on a line.** A quote has a contractor (the `Contractor` of
tasks, chosen or created from one field by name), an amount, a date, a validity, a status
(requested, received, accepted, rejected), a note, files and room for a Paperless-ngx
document (an identifier and a link, kept for a later lot and read by nothing yet). Accepting
sets the status and the line together (`accept_quote`); the line must belong to the
project. Only an accepted quote holds a line: leaving the status releases it, and deleting
a line sends its accepted quotes back to *received*. The database enforces it with a check
constraint (accepted implies a line). Several quotes may be accepted on one line, and
nothing forbids accepting two competing quotes: it is the person's decision, and the
commitment simply adds up.

**Money is `Decimal`, exact, in the currency of the home.** A column holds 12 digits and
two decimals, so 0 to 9,999,999,999.99, with a check constraint against negative amounts.
The services refuse a float, a boolean, `NaN`, an infinity, a negative amount, a third
decimal or an amount above the maximum before the model sees it (a `NaN` makes a comparison
raise instead of fail validation). Sums are made in Python on `Decimal`, never by SQL
`SUM`, which SQLite computes in floating point. The API gives amounts as strings with two
decimals, and the schema says `string`. Screens format them with the locale of the reader.

**Photos and files use the rules of attachments.** One table, `ProjectFile`, holds the
photos of a project (images only) and the files of a quote (images, or the documents of the
allow-list of ADR 0034, checked by content). Images are decoded and written again without
their metadata (ADR 0030). Files live under `MEDIA_ROOT/projects/<home id>/`, declared with
`homes.files.register_media_folder`, counted by the quotas of the home (every write goes
through `quotas.room_for`), erased from the disk when the record or the project is
deleted, and sent only by views that check the home, with `nosniff` and a sandbox policy.
At most 30 photos per project and 5 files per quote.

**The annual envelope** is a table, `AnnualEnvelope` (home, year, amount), because the home
model belongs to another lot. The list of projects shows the envelope of the current year,
the planned budget of the projects not finished nor abandoned, what is paid, and what is
left; the screen says so in words when the plans exceed the envelope. A later lot
consolidates the budget by room, project and task.

**Erasing a home or an account.** `Quote.budget_line` is `CASCADE`. The database refuses an
accepted quote without a line (`quote_accepted_has_line`), so `SET_NULL` made the erasure of a
home or of an account fail as soon as one quote was accepted. The services never erase a line:
they soft-delete it and send its accepted quotes back to Received first. Only the erasure of the
home, which removes every row of it, reaches the cascade, and the quotes go with it anyway.
`PROTECT` was rejected: it would make the erasure impossible, against ADR 0023.

**Isolation.** Every query goes through the home; a line, a quote, a task, a room or a
contractor is checked against the home of the project on the web and in the API. Owners and
members write, read-only members read (ADR 0020), and the services check the role
themselves. A project belongs to the home, not to a person: an API token with the `write`
scope may change it, and a token bound to another home sees nothing.

**API.** `projects`, `budget-lines`, `quotes` (with `accept`), `project-files`
(`content` and `thumbnail`), `project-tasks` and `envelope`, each matched to the web routes
in `parity.py`. The audit log (ADR 0045) records the title of the project and the names of
the fields changed, never an amount, a goal or a note. The export has the sections
`projects`, `project_budget_lines` (with the derived `committed`), `project_quotes`,
`project_files`, `project_tasks` and `project_envelopes`; the files go under
`files/projects/`.

## Out of scope

Inspiration links with a preview of the page (title and image fetched by the server) come
in a following change, behind the same guard against requests to private services as the
notifications (ADR 0043) and an instance setting (ADR 0035). The check of payments against
Sure, the opening of a Paperless-ngx document, the consolidation of budgets and the
purchase forecast belong to later lots.
