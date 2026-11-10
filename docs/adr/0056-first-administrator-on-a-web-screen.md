# 0056. First administrator on a web screen, with a one-time code of the log

- Status: accepted
- Date: 2026-11-10
- Extends: [0007](0007-authentication-and-api-tokens.md) (authentication and bootstrap),
  [0022](0022-instance-administrator-without-content.md) (instance administrator)

## Context

Without single sign-on, the first administrator was created with `manage.py
createsuperuser`, a command line in the container. On an installation without a shell
(Home Assistant OS, a managed container platform) that is nearly impossible. ADR 0007
announced "a local administrator bootstrap with a one-time installation token". The
maintainer decided on 2026-11-10 that it is a web screen protected by a code written in
the process log.

The risk is the usual one of a first-run screen: until the administrator exists, whoever
reaches the address could take the instance. The log is read by the operator only, so a
secret written there proves access to the server.

## Decision

**The code.** At each start, after the migrations, the entry point runs `manage.py
setup_code`. While no active account is both *staff* and *superuser* (and the screen is
not switched off), it creates a code and writes it on standard error with the address of
the screen. Nothing is written, and the unused codes are deleted, once an administrator
exists.

- 160 bits from `secrets` (`token_bytes(20)`), written in Base32 in eight groups of four
  (`ABCD-EFGH-...`), typed back without regard to case, spaces or hyphens.
- Stored as a SHA-256 digest in `accounts.SetupCode` with its expiry and the time of use.
  A fast hash is enough for 160 random bits (the argument of ADR 0007 for API tokens).
- **Valid for one hour.** Long enough to deploy, read the log and fill in a form; short
  enough that a code left in an archived log is dead soon. A restart, or `manage
  setup_code`, issues a new one and deletes the unused ones, so at most one code works.
- Compared in constant time (`hmac.compare_digest` against every candidate, none skipped).
  A wrong, an expired and a used code get the same message.

**The screen** `/setup/` (`accounts.views.SetupView`): code, name, email address and
password (Django's password rules, checked against the address and the name). It creates
the administrator (`is_staff`, `is_superuser`), with a verified primary address (the
operator proved control of the server), signs the person in and opens the administration
of the instance. It answers 404 as soon as an active administrator exists or when
`HOUSECAIRN_SETUP_SCREEN=false` (default `true`). The sign-in page shows a notice with a
link to it while it is open; it does not redirect, so that the people who already have an
account still sign in.

**Safe against two sends at once.** The code is claimed by a conditional `UPDATE ...
WHERE used_at IS NULL AND expires_at > now`, inside the transaction that creates the
account: of two simultaneous sends only one changes a row (on PostgreSQL the second waits
for the first one's row lock and then matches nothing), the other is refused. Any later
failure (address taken, password refused after the claim) rolls the claim back, so the
code stays usable. When the instance has no account at all, the single `InstanceSetup`
row (ADR 0007) is inserted in the same transaction, so the screen and an OIDC first
sign-in cannot both succeed.

**Limits and audit.** Each look and each try counts against `housecairn_setup`
(`10/m/ip,60/h/ip`, allauth's mechanism), over which the page answers 429. The form is
CSRF-protected, sent `no-store`, and never writes the code back into the page. The
creation is in the audit log of the instance (`instance.first_admin_created`, `by:
setup_screen`) and logged on `housecairn.security`; neither carries the code. The
`InstanceSetup` row records the method `setup_screen`.

## The three ways in, together

- **Single sign-on** (`HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL`, ADR 0007) is unchanged. While the
  instance has never had an account, the first OIDC sign-in still becomes the
  administrator.
- **`createsuperuser`** is unchanged.
- **The screen** is open while there is no administrator. Whichever of the three creates
  the first administrator first closes the other two: after an OIDC bootstrap or
  `createsuperuser` there is an administrator, so the screen is a 404; after the screen,
  `InstanceSetup` exists, so OIDC creates no administrator. Two accounts are never made
  administrators at once by two different ways, since each way writes the same
  `InstanceSetup` row or sees the administrator the other made.

## Alternatives

- **A token in an environment variable.** Works without a log, but a secret in a Compose
  file or a platform's variables is long-lived and often committed; a log code is born
  at start and dies after an hour. Rejected as the default.
- **Redirect the sign-in page to the screen.** More direct on a new instance, but it
  locks out the people who have accounts when the instance has no administrator (open
  sign-up). A notice with a link does not.
- **A code with no expiry, valid until used.** Simpler, but it stays valid in every log
  archive. Rejected.

## Consequences

- A log shipper that archives the container's output keeps the code for as long as it
  keeps the log; the code is dead after one hour or one use, and after the first
  administrator exists. An operator who forwards logs to a place read by others, and who
  uses single sign-on, sets `HOUSECAIRN_SETUP_SCREEN=false`.
- An instance with accounts but no active administrator (every administrator deleted in the
  database, or sign-up open before any administrator) gets the screen again at the next
  start: it is also the recovery path.
- `setup_code` failing never stops the container: `createsuperuser` remains.
