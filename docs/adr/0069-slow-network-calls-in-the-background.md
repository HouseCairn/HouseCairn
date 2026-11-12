# 0069. Reading a link's page and testing a channel run in the background worker

- Status: accepted
- Date: 2026-11-12
- Amends: [0043](0043-notifications-through-apprise.md) (*Test message*) and
  [0050](0050-projects-quotes-and-budget-lines.md) (*Links of inspiration*); builds on
  [0008](0008-background-tasks.md)

## Context

Two actions made the server call a stranger's server during the web request: reading the
page of an inspiration link (up to 10 seconds, page and picture together) and sending the
test message of a notification channel (up to 8 seconds). The web server runs two
synchronous workers by default, so one member could freeze the interface for everyone for a
few seconds, and a few of them for good. An external audit pointed it out on 2026-11-11, and
the maintainer decided that both go to the background worker that already exists.

## Decision

- **The existing worker, nothing new.** Both are tasks of the django-q2 worker that the
  entry point already starts and supervises (ADR 0008), queued by a service with
  `async_task`, as the archive of a large home is (ADR 0048). No second mechanism, no new
  dependency.
- **The request saves, queues, answers.** Adding a link saves it with its address, as
  typed, and queues `projects.links.read_preview`. The test of a channel records
  `test_state = running` and queues `notifications.tasks.send_test`. Neither request opens a
  connection to another server. The checks that need no network (rights, address,
  quota, rate limits) stay in the request and run before anything is queued.
- **The state is in the row.** `ProjectLink.preview_state` (`""`, `running`, `done`,
  `failed`) and `Channel.test_state` (`""`, `running`, `sent`, `failed`, `private`) with the
  time they started; no new table. The task changes the row only where it is still the same
  `running` (same start time). A task that comes late, or is given again, applies the
  deadline to the row as it is when it starts and leaves if the row is no longer `running`:
  it reads or sends nothing. The same holds for a reading started on an instance whose
  administrator has turned the preview off since: the row goes back to empty and the page
  is not read.
- **A task never stays "running".** The worker stops a task after 25 seconds
  (`timeout` of the task, under the 300 seconds of the cluster), and every read of a state
  (page, status fragment, API) first marks as `failed` a `running` that started more than 30
  seconds ago (`expire_preview`, `expire_test`), whatever became of the worker: stopped,
  restarted, queue lost. django-q2 gives a task back after its `retry` delay when the worker
  stopped it at its timeout (its `TimeoutException` is a `SystemExit`, and a failure is not
  acknowledged by default): the tasks are queued with `ack_failure=True`, so that the
  failure ends the task, and a task that comes anyway after the deadline does nothing, as
  above. An error in the task is `failed`, and logged without the address. So is a page that
  cannot be read (refused by the guard, unreachable, a network error, not a web page): the
  row says `failed` and the screen says so, it does not end as `done`.
- **The guard is the same code.** The task calls `projects.preview.read`
  (`core.netguard`: public addresses only, pinned address, every redirect checked, size and
  time limited) and `notifications.outbound.deliver` (the guard of ADR 0043 and 0059)
  unchanged; the worker process installs the same socket guard at start-up (`outbound.install`
  in `AppConfig.ready`). Tests run the real guard from the task.
- **The screen.** A row or a block shows "in progress", then the result. With JavaScript
  the fragment asks the server for itself again every 2 seconds with HTMX
  (`hx-get`, `hx-trigger="load delay:2s"`, `hx-swap="outerHTML"`), at most 12 times, counted
  in the address (`?n=`) and not in the browser; past that, or once the state is final, the
  fragment has no `hx-get` and says to reload the page. Without JavaScript, nothing polls and
  a reload shows the result. The fragments answer `no-store`, and only to a person who may
  read the project, or to the owner of the channel (anyone else gets the same 404 as before).
- **The API.** `POST /api/v1/me/notification-channels/<id>/test/` answers `202` with
  `{"state", "detail"}` instead of `{"ok", "detail"}`; a channel carries `test_state`.
  A link carries `preview_state`; creating one answers `201` at once, before the page is read.

## Consequences

- A slow or hostile server holds a worker of the task pool (two by default) for at most 25
  seconds, not a web process. Several links added at once wait their turn in the queue: the
  rate limits of ADR 0050 and 0043 bound that.
- If the worker is down, a link stays as typed and a test says "could not be sent" after 30
  seconds; nothing waits for ever.
- The API changes for `POST .../test/`: a client that read `ok` reads `test_state` of the
  channel later. Noted in the release notes (upgrade).
- Two columns on links and three on channels, one migration each; no data to convert
  (existing rows have the empty state).
