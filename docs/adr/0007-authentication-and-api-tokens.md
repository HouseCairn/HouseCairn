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
`HOUSECAIRN_SIGNUP_OPEN=true`; sign-up through OIDC follows
`HOUSECAIRN_OIDC_SIGNUP_OPEN` (default true: the provider decides who may sign
in).

**API tokens** (`apitokens` app), deliberately minimal:

- secret `hc_` + 32 random bytes (URL-safe base64), shown once at creation;
- only its SHA-256 digest is stored, with a short prefix for display. A fast
  hash is enough because the secret has 256 bits of entropy (unlike a
  password); lookup is by digest;
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

- Home Assistant gets an `events` token for one home and cannot read or change
  anything else.
- A leaked database does not reveal usable tokens.
- Token management screens (create, list, revoke) come with the data and API
  lot; until then tokens are issued with `apitokens.services.issue_token` and
  listed or revoked in the admin.
