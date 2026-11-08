# 0020. Household roles and invitations

- Status: accepted
- Date: 2026-11-07

## Context

A home is shared by a household, a tenant or a craftsperson (ADR 0006 created
the `owner`, `member` and `read_only` roles). The public instance opens in beta
by invitation: nobody gets in without one, and inviting must not reveal who
already has an account. ADR 0007 left an extension point for invitations in
OIDC sign-up.

## Decision

**Roles.** Three, as in the specification: `owner` (everything, the household
included), `member` (tasks, projects, marking work done) and `read_only`
(reads). Only owners invite, change roles, remove members, revoke or resend
invitations and set the sign-in rule (ADR 0021); every member reads the
household. Rules live in `homes.services`, called by the web and the API.

**At least one owner.** Every change that could leave a home without an owner
(changing a role, removing a member, leaving) locks the home's memberships
(`select_for_update`) and refuses the change if no owner would remain. Making
someone owner while becoming a member is one transaction
(`transfer_ownership`). A removed membership is soft-deleted (ADR 0005); the
person and their API tokens stop seeing the home on the next request.

**Invitations** (`homes.Invitation`): an address, a home, a role.

- The link carries `hci_` and 32 random bytes; only the SHA-256 digest is
  stored, as for API tokens (ADR 0007).
- Used once: accepted, revoked or expired (7 days by default,
  `HOUSECAIRN_INVITATION_LIFETIME_DAYS`), it opens nothing. **Send again**
  replaces the secret and the expiry; the former link dies. One pending
  invitation per address and home.
- Every dead link (unknown, used, revoked, replaced, expired) gets the same
  404 page, without the home's name.
- Accepting requires an account whose address is the invited one, so a
  forwarded or stolen link is useless to another account; the acceptance locks
  the invitation row, so two simultaneous acceptances use it once. Someone
  already a member keeps their role.
- **Which links prove the address.** A link that went to the address by email
  and was shown to nobody proves, by being opened, that whoever opens it holds
  the mailbox: accepting it marks the account's address verified (and creates
  the account, verified, if there is none). A link the owner handed over (the
  instance sends no email) proves nothing about the address. It therefore
  **never creates an account** and never verifies an address: the visitor is
  shown the same page whether or not an account uses the address, asked to
  sign in with the invited address, and told that an account is otherwise
  created by the administrator or once the instance sends email. Otherwise the
  owner holding the link could create the invitee's account with a password of
  their own, or learn by trying whether it exists. An existing account whose
  address equals the invited one can accept such a link, as before: the owner
  typed that address, and a link that creates nothing and verifies nothing
  gives the account nothing it did not have.
- When sign-up is closed, the invitation is the way in: the invitation page
  of an emailed link creates the account (password checked by the usual
  validators) with the invited address, then accepts. Through OIDC,
  `has_invitation` lets an identity sign up when a pending invitation exists
  for an address the provider asserts as verified; such accounts have no
  administration right.
- **One pending invitation per address and home**, in Python and by a partial
  unique constraint on the lower-cased address in the database
  (`unique_pending_invitation`): of two simultaneous requests, one fails. A
  lapsed invitation is revoked when a new one is made for its address.
- **Delivery.** With outgoing email (`EMAIL_HOST` and a delivering backend),
  the link is emailed, in plain text and HTML, in the inviter's language, and
  never shown to the inviter. Without email, the link is shown once to the
  inviter (and returned once by the API). The email is sent after the
  invitation is saved, outside any transaction of ours: if the mail server
  fails, the invitation stays, the failure is logged without the address, and
  the owner is told to send it again (a warning in the interface, a 503 with
  `code: delivery_failed` and the invitation `id` in the API). Links use
  `HOUSECAIRN_SITE_URL`, else the request's host, which `ALLOWED_HOSTS` has
  checked; `check --deploy` warns when email is on without it. The subject is
  folded to one line, so a home's name cannot add a header.
- **No enumeration.** Inviting answers the same, sends the same email and
  stores the same row whether or not the address has an account. On the page
  of an emailed link, whoever holds it is the mailbox's owner and may learn
  that an account uses that address: it is the one piece of information the
  invitation is about. A handed-over link tells nobody anything (above).
- **Rate limits**, by django-allauth's limiter and cache, configured in
  `ACCOUNT_RATE_LIMITS`: `housecairn_invite` (10 a minute and 50 a day per
  person) for creating and sending again; `housecairn_invitation` (30 a minute
  per client address, `REMOTE_ADDR` as set by the trusted proxy handling of
  ADR 0012) for opening and accepting links, GET requests included. The
  allauth helper that skips GET is bypassed for its internal function, pinned
  by the lock file and covered by tests.

**API.** Members (`/api/v1/homes/<id>/members/`, role change, removal,
`make-owner`), leaving (`/leave/`), invitations (`/invitations/`, revocation,
`resend`) and acceptance (`/api/v1/invitations/accept/`). **An API token never
changes who belongs to a home** (`NoTokenForHousehold`): with `read` it lists
members, but inviting, changing roles, removing, leaving, accepting and
creating a home need a signed-in session. A leaked integration token must not
let anyone in. Creating an account from an invitation stays a web page, as all
account management does (ADR 0003).

## Consequences

- Rate limits use Django's cache, per process by default; ADR 0025 describes
  how to share the counters.
- The administrator's invitations to the instance and the administrator's lack
  of access to content are ADR 0022; the audit of roles and invitations is
  ADR 0023.
- Leaving a home never needs the sign-in provider the home requires
  (ADR 0021), and removing a member or leaving asks for confirmation first.
- Owners see members' addresses; members see each other's, as a household
  does.
