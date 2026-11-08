# 0037. Today, My home, History and display preferences

- Status: accepted
- Date: 2026-11-08

## Context

Lot 6a gave tasks, occurrences and "Done" with undo. What is missing is the way
people look at them: the partner who opens the application wants to see what is due,
the person who runs the home wants to see what was done and what it cost, and nobody
wants to set up a view before using one. The product brief asks for an urgency order
by default, which each person can change.

## Decision

**Three reading screens, no new write path.** *Today* (`/h/<home>/today/`) lists the
open occurrences of one home. *My home* (`/me/`) gathers what concerns the person in
one home or in all of them. *History* (`/h/<home>/history/`) lists what was done or
skipped. They read through `tasks.agenda`, a module of queries and layout that web
and API both call, on top of the queries of `tasks.services`; rows are still closed
by the existing `complete` and `undo` services, so "Done" in one tap is the same
call as everywhere (ADR 0033).

**Today.** Open occurrences not hidden by their task, in four parts:

1. *Overdue* always comes first, whatever the layout (oldest first, then the more
   important task first).
2. What falls from today to the horizon (1 or 2 weeks, 1, 2 or 3 months), laid out
   by the person's choice: *urgency* (today, then coming up), *room*, *person* (the
   assignee) or *calendar* (one section per day). Inside a section the order is the
   urgency order.
3. *In season*: tasks with a season window that contains today, due beyond the
   horizon or without a date.
4. The materials to buy belong to the stock and arrive with it.

Each part can be switched off. Every list is cut at 200 rows: Today is a glance,
History is the report.

**My home.** For each home the person belongs to (all, or the one chosen): the open
tasks assigned to them; what is overdue for someone else or for nobody; open tasks
nobody has taken (not overdue); items whose warranty ends within 60 days. The three
task lists share no row. Homes that require a sign-in provider the session did not
use are not shown, as everywhere (ADR 0021).

**History.** Done and skipped occurrences, most recent first, filtered by room, item,
contractor, person who closed it, outcome and dates, and searched in the title and
the note. A skipped occurrence has no completion date: the day it was closed stands
for it. The screen shows the sum of the real costs *that were entered* and over how
many entries; an occurrence without a cost counts for nothing, not for zero. The CSV
export and the PDF file are a later lot (data).

**Display preferences belong to the person**, not to a home: a model `DisplayPreference`
in the `tasks` app (one row per user at most, created on the first change; defaults
apply until then), not a field of the account, so that the accounts app does not learn
about tasks. They are read and changed only for the person signed in, by the web
(`/me/preferences/`) and by the API (`/api/v1/me/display-preferences/`). An API token
may read them; changing them is for the person signed in (ADR 0045). The row goes with the account when it is erased.

**API.** `GET /api/v1/homes/<id>/today/`, `GET /api/v1/me/home/` (optional `home`),
`GET|PATCH /api/v1/me/display-preferences/`. History is the occurrence list with the
filters `contractor`, `completed_by`, `q`, `closed_after`, `closed_before`, the order
`ordering=recent`, and `GET .../occurrences/cost/` for the total.

## Consequences

- A person who never opens the preferences gets the urgency layout over one week.
- Changing the layout never moves or hides a task for someone else.
- The sum in History is partial by construction and says so.
- Today does not paginate; a home with more than 200 open tasks in one part sees the
  oldest 200 of that part and finds the rest in the task list.
