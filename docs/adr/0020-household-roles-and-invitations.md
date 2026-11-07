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
- When sign-up is closed, the invitation is the way in: the invitation page
  creates the account (password checked by the usual validators) with the
  invited address, then accepts. Through OIDC, `has_invitation` lets an
  identity sign up when a pending invitation exists for an address the
  provider asserts as verified; such accounts have no administration right.
- **Delivery.** With outgoing email (`EMAIL_HOST` and a delivering backend),
  the link is emailed, in plain text and HTML, in the inviter's language, and
  never shown to the inviter; opening it then proves the address, so the new
  account's address is marked verified. Without email, the link is shown once
  to the inviter (and returned once by the API), and the address is not marked
  verified. Links use `HOUSECAIRN_SITE_URL`, else the request's host, which
  `ALLOWED_HOSTS` has checked. The subject is folded to one line, so a home's
  name cannot add a header.
- **No enumeration.** Inviting answers the same, sends the same email and
  stores the same row whether or not the address has an account. On the
  invitation page, whoever holds the link (the invited address) may learn
  that an account uses that address: it is the one piece of information the
  invitation is about.
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

- Rate limits use Django's cache. The default local-memory cache counts per
  process: with several web workers, a limit is per worker. A shared cache can
  be configured later without changing the code.
- The instance administrator's own invitations (to create a home on the
  instance) and the administrator's lack of access to content come with the
  next part of this lot.
- Owners see members' addresses; members see each other's, as a household
  does.
