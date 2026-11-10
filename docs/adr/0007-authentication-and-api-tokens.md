# 0007. django-allauth, scoped API tokens, OAuth 2 later

- Status: accepted
- Date: 2026-11-07

## Context

People sign in with a local account (with a second factor or a passkey) or
through their own identity provider. Integrations such as Home Assistant need a
credential limited to what they do. The future iOS app needs a proper OAuth 2
flow. Changing the user model after the first migration is painful in Django.

## Decision

**User model.** `accounts.User` from the first migration: UUID primary key,
email as identifier, no username.

**Interactive sign-in.** django-allauth: local accounts with email, TOTP,
recovery codes and passkeys (WebAuthn, passkey login enabled); generic OpenID
Connect through the `openid_connect` provider, enabled only when
`OIDC_SERVER_URL` and `OIDC_CLIENT_ID` are set, with PKCE. No identity provider
is named in the code. Local sign-up is closed unless
`HOUSECAIRN_SIGNUP_OPEN=true`; the sign-in page only links to it when it is
open. A local administrator bootstrap with a one-time code written in the log is
described in [ADR 0056](0056-first-administrator-on-a-web-screen.md).

**Sign-up through OIDC is closed by default** (`HOUSECAIRN_OIDC_SIGNUP=closed`).
An identity the provider accepts but that has no account here is refused, with
a translated page asking the administrator for access. An existing local
account is never taken over by an identity that merely shares its address: it
links its OIDC identity once signed in. Three exceptions, decided in
`accounts.services.oidc_signup_decision`:

1. **Bootstrap.** While the instance has never had an account, the first OIDC
   sign-in creates the account with instance administration rights
   (`is_staff`, `is_superuser`). If `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL` is set,
   only an identity whose address matches it (case-insensitively) and whose
   `email_verified` claim is the JSON value `true` can do so; any other is
   refused, even with sign-up open. The single-row `accounts.InstanceSetup`
   table, written in the same transaction as the account, makes this happen
   once: of two simultaneous first sign-ins, one inserts the row and the other
   fails on its fixed primary key (with SQLite, it waits for the first and then
   sees the account), and is then handled as any later sign-in. The row is also
   written when the first account is created any other way (`createsuperuser`,
   admin site, data migration) and is never removed, so the rule does not come
   back even if every account is deleted. The creation logs a `WARNING` on the
   `housecairn.security` logger, "first account created as instance
   administrator via OIDC", with the account's identifier and nothing else; the
   row records the method, the account and the time, read-only in the admin.
2. **Open sign-up.** `HOUSECAIRN_OIDC_SIGNUP=open` lets anyone the provider
   accepts create an account, without any administration right.
3. **Invitation.** `accounts.services.has_invitation` is where invitations will
   plug in with account management; it returns false until then. An invited
   account has no administration right either.

**API tokens** (`apitokens` app), deliberately minimal:

- secret `hc_` + 32 random bytes (URL-safe base64), shown once at creation;
- only its SHA-256 digest is stored, with a short prefix for display. A fast
  hash is enough because the secret has 256 bits of entropy (unlike a
  password); lookup is by digest, so a timing difference could reveal at most
  part of a digest, which says nothing about the secret;
- scopes `read` (safe methods), `write` (other methods), `events` (only the
  endpoints that declare `token_scope = Scope.EVENTS`, such as
  `POST /api/v1/homes/<home_id>/events/`; nothing else). Scopes do not imply
  each other;
- bound to at least one home, among the user's; the token never sees more than
  its user, and loses a home when the user loses the membership;
- expiry (90 days by default, `HOUSECAIRN_API_TOKEN_DEFAULT_LIFETIME_DAYS`;
  never-expiring tokens only on explicit request), revocation, soft deletion,
  last use recorded at most once a minute;
- `ApiTokenAuthentication` (`Authorization: Bearer hc_...`) and
  `TokenScopePermission` are DRF defaults.

**OAuth 2 for the iOS app: not now.** When the app starts, django-oauth-toolkit
will be added as an OAuth 2 authorization server, authorization code flow with
PKCE and no client secret (public client), mounted at `/o/`. Its access tokens
will be checked by an extra DRF authentication class placed before
`ApiTokenAuthentication`; its scopes will map to the same `read`, `write` and
`events` values, and `homes_for` will narrow by the homes granted at consent.
Nothing in the API or the services changes for it.

## Consequences

- **Bootstrap risk.** Until the first account exists, the first person the
  identity provider lets through becomes the instance administrator. Set
  `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL` to the administrator's address before the
  first start, and sign in right after installation. An operator who prefers
  no OIDC bootstrap creates the first account with `manage.py createsuperuser`
  before enabling OIDC.
- Closing sign-up does not restrict who the provider authenticates: limiting
  the application's client to a group at the provider remains the operator's
  choice, and is what `open` relies on.
- Home Assistant gets an `events` token for one home and cannot read or change
  anything else.
- A leaked database does not reveal usable tokens.
- Token management screens (create, list, revoke) come with the data and API
  lot; until then tokens are issued with `apitokens.services.issue_token` and
  listed or revoked in the admin.
