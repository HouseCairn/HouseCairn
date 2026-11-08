# 0031. Tasks, occurrences and recurrence

- Status: accepted
- Date: 2026-11-08

## Context

A task is something to do once or again and again: change the battery of a smoke
detector every year, mow the lawn every week from April to October, repaint the
living room. Closing it must take one gesture for every task, repeating or not,
and a repeating task must never be left without its next date. The date arithmetic
(month ends, leap years, intervals) is the part most often written wrong, and
ADR 0001 rules out writing code that a maintained library already provides.

## Decision

**Two tables** (app `tasks`, every one a `HomeOwnedModel`, ADR 0005 and 0006):

- `Task`: the thing to do. Only the title is required. Optional: room and item
  (the room follows the item), priority, estimated duration, labour and material
  budgets, notes, a procedure in Markdown, the assignee (a member of the home) and
  a contractor, and the rule of repetition. The materials with quantities belong to
  the stock (a later lot) and will hang off the task by their own table.
- `Occurrence`: one time the task has to be done, with its due date, its status
  (*planned*, *done*, *postponed*, *skipped*) and, once closed, the date, the real
  cost and a note. A task has **exactly one open occurrence** (planned or postponed),
  enforced by a partial unique index; closing it creates the next one in the same
  transaction. A task done once, closed, has none.
- `Contractor`: name, trade, a note: a plain entity of the home.

**Library.** The rules are evaluated by **python-dateutil** (`rrule`,
`relativedelta`), the reference Python implementation of the recurrence rules of
RFC 5545. It is already a runtime dependency (ADR 0001, "needed from the tasks lot
onwards"), so this adds no code to ship. Compared on 2026-11-08, from PyPI:

| Candidate | License | Remark |
| --- | --- | --- |
| python-dateutil 4.0.0 (2026-11-01) | BSD-3-Clause | Already installed. Pure Python, no native code, no network. |
| icalendar 7.3.0 + recurring-ical-events 3.8.2 | BSD-2-Clause, LGPL-3.0-or-later | Meant to expand the events of a calendar file; two more packages and an LGPL one for a function dateutil provides. Worth another look for the ICS feed of J3. |
| django-recurrence 1.14 | BSD | Wraps dateutil and adds a form widget with its own scripts, which the policy of ADR 0011 does not allow as it is. |

No rule is ever parsed from text: `rrulestr` is not used, the rule is built from
validated fields (mode, unit, interval, season), so no input of a user reaches the
parser of the library. The module `tasks/recurrence.py` is pure functions on dates
and carries the property tests.

**Modes.**

- *Once*: no next date.
- *Fixed date*: every N days, weeks, months or years from the first date, which
  is stored on the task (`series_start`) because it carries the day of the month.
  The next date is the first date of the series strictly after both the due date
  and the day it was closed: a task done long after does not bring back each missed
  date, the open occurrence is the arrears. The count does not start at the anchor but
  one interval before the reference date: a series is the anchor plus a whole number
  of intervals, so the dates are the same and the cost no longer depends on the age
  of the task. The day of the month still comes from the anchor.
- *After the last time*: the closing day plus the interval, by `relativedelta`.

**Month ends.** A series anchored on the 29th, 30th or 31st falls on the last day
of the months that are shorter (BYMONTHDAY=(day, -1) with BYSETPOS=1: the smaller of
the two), and one anchored on 29 February falls on 28 February in other years.
Without that, the RFC skips the month, which no one expects of "every month on the
31st".

**Season.** A window of months (it may run over the new year). A date outside of it
moves to the first day of the next season. **Masking**: an occurrence carries
`visible_from`, its date minus N days, and the lists hide it until then, so that the
filter stays a plain query.

**Not in this lot**: rules on usage (counters) and on sensor events (J3).

**Procedure in Markdown.** The text is rendered by markdown-it-py (MIT, added to
ADR 0001): raw HTML is not parsed (it is shown as text), images are disabled so that
nothing is loaded from anywhere (ADR 0011), and a link is kept only if it is `http`
or `https`, with `rel="noopener noreferrer nofollow"`; any other link (`javascript:`,
`data:`, a relative address) keeps its words and loses its address.

**Addresses** (ADR 0010): `/h/<home>/tasks/<uuid>/`, and `/api/v1/homes/<home>/tasks/`,
`occurrences/`, `contractors/`. An unknown identifier and one of another home answer
the same 404.

## Consequences

- Web and API call the same functions of `tasks.services` (ADR 0002); the screens
  of the next lot (today, history) read through `open_occurrences`, `overdue`,
  `upcoming` and `done`.
- Tasks, occurrences and contractors are registered in the export of a home (ADR
  0023) and go with the home when it is deleted (their rows hang off it).
- A rule that needs a new unit or a new mode changes `recurrence.py` and its tests
  only.
- Dates in the far future are bounded (intervals of about fifty years at most); a
  series that would pass the year 9999 simply ends.
