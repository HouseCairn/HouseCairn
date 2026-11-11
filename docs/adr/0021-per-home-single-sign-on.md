# 0021. Single sign-on required per home

- Status: accepted, partly superseded by [0057](0057-api-tokens-of-a-home-that-requires-a-provider.md)
- Date: 2026-11-07

> **Note (2026-11-10).** The clause "API tokens never open a home that requires a
> provider" and the first consequence below are superseded by
> [ADR 0057](0057-api-tokens-of-a-home-that-requires-a-provider.md): a token created from
> a session signed in through the provider records it, and opens the home while the home
> requires that provider or nothing. The rest of this record stands.

## Context

Sign-in belongs to the person, not to the home: one person can belong to
several homes. On a shared instance, some households want their members to
sign in through their own identity provider; others use the built-in sign-in
(password, passkey, second factor). A provider configured by each home was
considered and set aside: a malicious provider could assert another user's
address and take over their account.

## Decision

- **Providers are declared by the instance administrator only** (the `OIDC_*`
  variables, ADR 0007). Single sign-on is never required for the whole
  instance.
- **A home may require one declared provider** (`Home.required_provider`,
  empty by default). Only an owner sets it, only to a declared provider, and
  only from a session signed in through that provider, so that an owner cannot
  lock out the session that sets the rule nor name a provider nobody can use.
- **The check is made when the home is opened**, in one place:
  `HomeScopedMixin.get_home` and `get_homes` (web and API). A request
  satisfies the rule when the session's authentication records, kept by
  django-allauth server-side, include a sign-in through that provider.
  Nothing the client sends counts. Lists still show such homes, marked
  `locked`, so the member knows which provider opens them; reading or changing
  one answers a page that offers to continue with the provider (web, 403) or
  `403` with `"code": "sso_required"` and the provider (API).
- **API tokens never open a home that requires a provider**: a token is not a
  sign-in through it, and recording how a token was issued is left to the
  token management screens.
- **No account is reached through a matching address**:
  `SOCIALACCOUNT_EMAIL_AUTHENTICATION` and its auto-connect stay off. An
  identity signs in only to the account it is linked to; a person links it
  once signed in.

## Consequences

- A home that requires a provider cannot be reached by an integration token
  (for example Home Assistant's `events` token) until token management records
  the sign-in a token was issued from. To revisit then.
- If the administrator removes a provider, the homes requiring it stay locked
  until the rule is lifted, and the way out does not go through the
  administration site, which shows no home (ADR 0022): an owner opens the
  locked page, which offers **Remove the sign-in requirement** when the
  provider is no longer declared (web, and `POST /homes/<id>/unlock/`); and the
  administrator can clear the rule of every such home at once from the
  instance page, which reads none and reports a count. A provider that is
  still declared keeps its protection: neither action touches it.
- A member is never held in a locked home: leaving it, the member page and the
  API `leave` need no sign-in through the provider.
- The rule binds a session, not an account: a member who signed in through the
  provider once in the session keeps access until that session ends.
