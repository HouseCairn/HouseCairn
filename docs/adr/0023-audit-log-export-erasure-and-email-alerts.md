# 0023. Audit log, export, erasure and security emails

- Status: accepted
- Date: 2026-11-08

## Context

The public instance needs what a controller of personal data owes people:
knowing who did what to a household, taking the data out, erasing it, and
learning of sign-ins and changes to their account. The specification asks for a
complete export "in open formats", a definitive deletion of a home and of an
account, and an audit log of roles, invitations, exports and administration.

## Decision

**Audit log** (`audit.AuditEvent`). One row per sensitive operation: when, the
action, the person who did it, the person it concerned, and a short `detail`
whose keys are a closed list (role, provider identifier, count); a content
value is refused by `audit.record`. Two scopes. A **home** entry carries the
identifier of the home (not a foreign key: it is deleted with the home) and is
read by that home's owners, in the interface and by the API (`/audit/`). An
**instance** entry has no home and is read by the administrators: invitations
to the instance, accounts created or erased, administration actions, homes
unlocked, a home deleted (without its name). A database constraint ties the
scope to the presence of a home. The administrator never sees a home entry, so
membership structure does not leak. References to people are `SET NULL`: an
erased account leaves entries that no longer say who. Invited addresses are not
stored in entries.

**Export** (`homes.exports`). The archive is a zip with `export.json` and
`files/`. `export.json` has `format`, `version` (1), `exported_at`, the home,
and one section per app, registered by the app that owns the data
(`exports.register`); files are registered the same way (`register_files`), so
a later lot cannot add a table the export forgets. Every exporter receives the
home and reads that home only; tests build two homes and look for the other's
name, address and events in the archive. Only owners export, signed in (no
token), and the export is recorded. Pending invitations are listed without
their link digest. The format is documented in Administration, Export and
deletion.

**Deletion of a home.** An owner types the exact name of the home. The home
and everything below it go by cascade, soft-deleted rows included, with its
audit entries and its directory of files; a token left without a home is
revoked. The specification asks for a definitive deletion and sets no grace
period, so there is none: the screen proposes the export first. The instance
log records that a home was deleted, without its name or identifier.

**Erasure of an account.** The person confirms with their address and, if the
account has a password, the password. Refused for the only administrator and
for an account that is the only owner of a home with other members (ownership
is handed over, or the home deleted, first), which is the last-owner rule of
ADR 0020 applied to erasure. Homes where the account is the only member go
with it; invitations to its address, accepted or not, are deleted; the account,
its sign-in methods, devices and tokens are deleted. An administrator erases
through the same service (ADR 0022).

**Emails.** One layout for all: allauth's messages in text, and an HTML version
built from the same translated text (`AccountAdapter.render_mail`), so the two
cannot drift; subjects begin with "HouseCairn:". Verification, reset, and the
alerts allauth sends (password changed or set, address changed, security key,
authenticator, recovery codes) are on whenever `EMAIL_HOST` is set. A **new
sign-in alert** is HouseCairn's own: a browser holds a random secret in a cookie
and the account keeps its digest (`KnownDevice`); a sign-in from a browser the
account does not know, once the account knows at least one, sends an alert with
the address and browser. The first device of an account raises none; at most 20
devices are kept; a failing mail server is logged, never an obstacle to signing
in. Without `EMAIL_HOST`, nothing is recorded or sent, and every page that
needs a mailbox (password reset, the address page, instance invitations) is
hidden, as the reset page already was. Links in emails use `HOUSECAIRN_SITE_URL`
when it is set, including the links allauth builds (`on_site`): `check --deploy`
warns when mail is on without it.

## Consequences

- Deleting a home cannot be undone; the interface says so and offers the
  export. A grace period can be added without changing the model if the
  specification asks for one.
- The audit log grows without limit; no purge is offered yet.
- The cookie of known devices is a convenience for alerts, not a security
  control: a thief with the cookie is not alerted, and a person who clears
  cookies gets an alert for their own browser.
