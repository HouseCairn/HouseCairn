# 0071. A demonstration instance: public accounts, nothing sent, reset every night

- Status: accepted
- Date: 2026-11-12
- Extends: [0008](0008-background-tasks.md) (background tasks),
  [0035](0035-instance-settings-in-the-interface.md) (instance settings in the interface)

## Context

A public instance at `demo.housecairn.app` lets people try HouseCairn without installing it.
Its accounts are public: anyone signs in as its administrator. Without limits, a visitor could
change the settings of the instance (open sign-up, a mail server of their own), make it send
email or notifications to anyone, use it to reach other hosts (link previews, the test of a
sign-in provider), take an account from the next visitors (a new password, a new address, a
second factor), or fill its disk.

## Decision

- **One variable, off by default.** `HOUSECAIRN_DEMO` (true or false, read strictly at start-up
  like the other boolean variables). False: nothing changes, which the tests check.
- **Two public accounts**, `admin@example.com` (administrator of the instance, owner of the
  home) and `user@example.com` (member, read and write), with the password `housecairn-demo`,
  and the home of `load_demo_data` in the default language of the instance. No second data set:
  the one that serves the screenshots serves the demonstration.
- **`reset_demo`** empties every table but those of the task worker (django-q2, which hold the
  reset's own schedule and task) and the content types and permissions of Django, in one
  transaction, after the uploaded files are removed; then it creates the accounts and the home
  again. It refuses to run while `HOUSECAIRN_DEMO` is false. The container runs it at start-up
  on an instance without any account (`--if-empty`); a django-q2 schedule runs it at 03:00 in
  Paris. Each run sets the next one again, so that the hour follows summer time: no system
  cron and no new dependency.
- **Refusals in the services, not the screens.** Every refusal raises `DemoRefusedError`, a
  `PermissionDenied`, in the service that the screen and the API share: changing or resetting
  a setting, adding, changing, deleting or testing a sign-in provider, testing the mail server,
  instance invitations, home invitations by email, the test of a notification channel or of a
  device. The API answers a 403 with the code `demo`; a screen shows the message on the page it
  came from (`demo.middleware`). The settings screens show their fields disabled.
- **Values imposed on the settings** (`demo.mode.FORCED`), above variables and database: sign-up
  closed, sign-up through a provider closed, no mail server, no preview of links, 2 MB per file,
  20 MB and 50 files per home. A quota of 200 MB for all homes together is added, since anyone
  can create homes. The API gives these settings the source `demo`.
- **Exports bounded.** The archives of the background export (ADR 0048) are outside the quota
  of files, so on a demonstration instance: one archive at a time for a home, at most five for
  the whole instance (20 MB each at most), and an archive is kept one hour instead of a day.
  Refused with the same message as the other refusals. With the mode off, nothing changes.
- **Nothing leaves the server**, by the last step of each way out: the mail backend sends
  nothing, `outbound.deliver` sends no notification, `devices.send` pushes nothing to a device,
  the reminder worker does nothing, the sign-in providers of the variables and of the interface
  are not offered.
- **Accounts guarded on their models**, so that every path is covered (screens, API, Django's
  administration site, allauth's forms, commands): outside `reset_demo`, no account is created;
  a public account keeps its address, password, rights and active state and is not deleted; no
  address, second factor or linked identity is added to or removed from it. A sign-in that
  hashes the same public password again is allowed. The first-account screen is closed. The
  places of the two accounts in the demonstration home (the home both belong to) are guarded
  the same way: no role changes, nobody leaves or is removed, and the home is not deleted.
  A home a visitor made for themselves stays theirs to change.
- **A read-only administration site.** In `/admin/` every model administration loses its add,
  change and delete permissions, and any request of the site that is not a read is refused
  with the message of the demonstration mode (signing in and out stay); the guards on the
  models stay behind it.
- **Sign-in failures counted by address only.** The limit of failed sign-ins per account
  (`ratelimit_login_failures`, ADR 0042) does not apply: the two accounts are public, and five
  wrong passwords for `admin@example.com` would lock every visitor out, again and again. The
  limit per address (ten a minute) stays. With the demonstration mode off, both limits apply
  as before.
- **A banner** on every page, and the two accounts on the sign-in screen.

## Consequences

- `createsuperuser` and every other way to create an account are refused on a demonstration
  instance: its accounts come from `reset_demo` alone.
- What a visitor enters is public until the next reset, which the banner says.
- A visitor still changes the content of the demonstration home and the display names; the
  nightly reset puts them back.
- The demonstration mode does not replace the rate limits of the instance, which stay those of
  ADR 0042, nor a reverse proxy that limits requests.
