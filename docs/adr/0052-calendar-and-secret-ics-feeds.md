# 0052. Calendar views and secret, revocable iCalendar feeds

- Status: accepted
- Date: 2026-11-08

## Context

A task is easier to plan when it can be seen on a calendar, and people already read their day
in Google Calendar, Apple Calendar, Thunderbird or Home Assistant. The project integrates
rather than reinvents (rule 1): it shows a calendar of its own, and publishes the same data as
an iCalendar feed that those applications subscribe to. A feed is read by an application that
cannot sign in, so its address is the credential.

## Decision

**A new app, `calendar`**, with one table, `Feed`. It reads occurrences through the models of
`tasks` and changes nothing there. The only edits outside it are one-line hooks: settings, the
two URL files, the registry of web/API parity, the help page, the tab of the tasks, the
labels of the audit log and one rate limit.

**One read function for everything.** `calendar.services.entries(user, homes, start, end,
filters)` serves the week, month and year screens, the API and the feed (ADR 0002, 0003). It
makes at most three queries whatever the number of tasks: the roles of the person, the
occurrences whose day falls in the range, and the open occurrences of the tasks that repeat. A
test counts them with 1 and with 26 tasks. The range is at most 400 days and 5 000 entries; the
answer says when it was cut. The entries come day by day: the real occurrences and the
forecast of every task are merged in ascending order (`heapq.merge`) and the merge stops at the
limit, so a cut removes the farthest dates and never a near date of one task while a far date
of another stays. The same holds past 1 000 repeating tasks: the 1 000 whose open occurrence
is the earliest are projected, and the answer says it was cut.

- **The day of an occurrence** is its due date, or, when it has none, its completion date. A
  task done late stays on the day it was due, with the status "done".
- **Projections.** The dates after the open occurrence of a task that repeats are computed by
  `tasks.recurrence.next_due` (python-dateutil's RFC 5545 engine, the one that creates the next
  occurrence), were each occurrence closed on its due date, season included. Nothing is
  written. At most 400 steps per task and 1 000 tasks per range. A projected entry is
  `planned`, flagged `projected`, and has no Done button. Its identity is its task and its date.
- **Statuses in words**, on every screen: planned, done, postponed, skipped, and "forecast".
  Colour is never the only carrier; a skipped task is also struck through.
- **Done and Undo** are the existing buttons of `tasks` (ADR 0033), posted from the calendar
  with a `next` address; the page that comes back shows the undo banner. A reader sees the
  tasks and no button (and a POST is still a 403 in the service).
- **The person of a task** is named by the helper of ADR 0045 (`accounts.names.person_name`:
  the display name, then the full name, then the part of the address before the "@"), and two
  people of the same name in the filter are told apart by `labels`. The whole email address is
  never shown. The feed carries no person at all.

**The feed.**

- **Scope.** A person has at most one feed per home they belong to, and one combined feed for
  all their homes. It shows what the calendar shows without filters: the whole home, not only
  the tasks assigned to the person. "Personal" means the address belongs to the person.
  A home that requires a sign-in provider (ADR 0021) has no feed, and its feed stops: a bearer
  address cannot prove which provider opened a session.
- **Secret.** `secrets.token_urlsafe(32)`: 256 bits. Only its SHA-256 digest is stored, as for
  API tokens and invitations (ADR 0007, 0020); the address is shown once, in the answer that
  creates or regenerates the feed. **Regenerating** replaces the digest: the old address
  stops at once. **Revoking** deletes the row, a credential having nothing to restore.
- **No answer tells more than "no".** An unknown, a malformed and a revoked secret get the same
  404 with the same body and headers (`no-store`). A secret whose person is deactivated, or has
  left the home, is the same 404. The address is rate limited per client address (60 a minute,
  `housecairn_calendar_feed`), and over the limit answers 429.
- **Not an API token.** The address opens one document and nothing else; it carries no scope
  and is not accepted anywhere that reads a token. Managing feeds is for a session: **an API
  token of any scope is refused** on `/api/v1/me/calendar-feeds/`, since a token could
  otherwise obtain a credential that outlives it (rule: a token changes nothing that belongs
  to the person).
- **Revocation.** Leaving a home, or being removed from it, deletes the person's feed of that
  home: a `post_save` receiver on the membership (the same path whoever removes the member).
  The combined feed stays and no longer includes the home. Deleting an account or a home
  deletes its feeds by cascade. The audit log records creation, regeneration and revocation
  (with the cause "left" when a membership ended it), never the secret or its digest.
- **Content.** Title, home, room, date, status and a link to the task. No note, cost, procedure,
  attachment, person or email address. A test fills every such field and looks for them in the
  document. Dates are all-day events (`DTSTART;VALUE=DATE`); the window runs from 30 days
  before today to one year after, today being the day in the time zone of the person (their
  notification setting, else the instance's, ADR 0032). `X-WR-TIMEZONE` says which; the
  language is the person's too. A change of clock cannot move an all-day event.
- **Identity.** `UID` is `<occurrence id>@housecairn` for an occurrence, and
  `<task id>-<date>@housecairn` for one not created yet. `DTSTAMP` is the last change of the
  row, so the same data gives the same bytes: the `ETag` is a digest of the body and
  `If-None-Match` answers 304. `Cache-Control: private, max-age=900`, `Referrer-Policy:
  no-referrer`, `X-Robots-Tag: noindex`. `REFRESH-INTERVAL` and `X-PUBLISHED-TTL` suggest six
  hours; calendar applications are free to ignore them.
- **Format and escaping.** The document is written by the `icalendar` library, which escapes
  commas, semicolons, backslashes and line breaks and folds lines at 75 octets. Titles are also
  reduced to one line of printable characters first. A test puts `\r\nBEGIN:VEVENT` and
  `END:VCALENDAR` in a title and reads the document back: still one calendar, one event.

**Dependency: `icalendar`** (7.3, published 2026-08-19, more than the seven days of ADR 0014),
BSD-2-Clause, compatible with AGPL-3.0. It is the common Python library for reading and writing
iCalendar, maintained by the Plone community; it depends on python-dateutil and tzdata, already
in the lock. Writing RFC 5545 by hand (escaping, folding, parameters) is the kind of code that
breaks on a title nobody tried; the library also reads the document back in the tests, which is
the validity check. Added to the list of ADR 0001.

**Data.** The export of a home lists its feeds (`id`, creation and regeneration dates), never
the secret or its digest. Erasing a home or an account removes them.

## Consequences

- The address is a bearer secret: whoever has it reads the feed until it is regenerated or
  revoked. It travels in the URL, so access logs of a reverse proxy may keep it; the
  documentation says to treat it as a password.
- A feed shows the home to anybody the address is given to, readers included; a reader can
  have one.
- Not done here: a feed limited to the tasks assigned to the person, `VALARM` reminders (the
  [notifications](0043-notifications-through-apprise.md) do that), two-way sync (CalDAV), and a
  rate limit setting in the interface (the limit is fixed).
