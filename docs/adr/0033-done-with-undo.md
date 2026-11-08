# 0033. "Done" in one gesture, with undo

- Status: accepted
- Date: 2026-11-08

## Context

The partner of the person who set the application up will use it only if closing a
task is one tap, with no form and no question, on every task. A tap on a phone is
also a tap by mistake.

## Decision

**One call closes an occurrence.** `services.complete` marks the open occurrence
done (today unless a date is given, not in the future), records who did it, and
creates the next occurrence if the task repeats, in one transaction, under a row lock
so that two taps create one successor. The date, the real cost and a note can be
given with the call or filled in afterwards (`update_occurrence`). `skip` is the same
without being done; `postpone` moves the date and keeps the occurrence open with the
status *postponed* and the date it started from.

**Undo is a service, not a screen state.** `services.undo` takes back a closing: the
occurrence gets back the status it had (stored in `status_before`: *planned* or
*postponed*), loses its date, author, cost and note, and **the occurrence created by
the closing is deleted** (hard delete: it is derived data, nobody has seen it). The
state before and after is identical, which the tests compare field by field.

**Undo is refused when it would lose work.** If the occurrence created meanwhile has
been postponed, noted, given a cost, a photo, or closed, the call fails with a
message and nothing changes. The successor is found through a one-to-one link
(`follows`), so the undo is exact even if the due date was edited.

**The web** answers a button with a redirect carrying `?undo=<occurrence>`; the page
shows a banner with a button, which posts to the undo address. The identifier in the
address only decides what the banner offers: the post is checked like any other write
(role, home). The API has `POST .../occurrences/<id>/complete/` and `.../undo/`.

## Consequences

- No "are you sure" dialogs on Done; a wrong tap costs one more tap.
- Changing the completion date afterwards does not recompute the successor of a task
  that repeats after the last time; it keeps the date it was created with.
- An undo after the next occurrence moved is refused rather than guessed.
