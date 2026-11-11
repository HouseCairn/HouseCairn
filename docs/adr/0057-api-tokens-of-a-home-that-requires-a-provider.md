# 0057. API tokens of a home that requires a sign-in provider

- Status: accepted
- Date: 2026-11-10
- Supersedes: the clause "API tokens never open a home that requires a provider" of
  [0021](0021-per-home-single-sign-on.md), and its first consequence
- Extends: [0007](0007-authentication-and-api-tokens.md) (API tokens)

## Context

ADR 0021 lets a home require a sign-in provider, checked when the home is opened, and
decided that no API token opens such a home: a token is not a sign-in through the
provider, and recording how a token was issued was left to the token screens. Those
screens exist (`apitokens`), and the result is that a member of such a home cannot
connect any integration to it, Home Assistant included: the screen does not offer the
home, and with no other home the **Create a token** button is gone. The maintainer
decided on 2026-11-10 that this is wrong: a person of a home that requires a provider
must be able to create a token for it, in the spirit of the requirement.

The requirement says: this home is opened only by someone who has just proved, through
that provider, who they are. A token is used without any sign-in, so the question is
what proof it can carry.

## Decision

- **A token is bound to a home that requires a provider only from a session signed in
  through that provider**, the very check that opens the home on the web
  (`homes.sso.signed_in_providers`, the authentication records django-allauth keeps
  server-side). From a session signed in with a password or a passkey, the screen lists
  the home disabled, says why, and offers to continue with the provider, back to the
  form; a forged request is refused by the service (`apitokens.services.create_token`):
  the form shows an error, `POST /api/v1/me/tokens/` answers `403` with
  `"code": "sso_required"`.
- **The token records that provider** (`ApiToken.signed_in_provider`), only when a home
  of the token requires it, so it is one the session did sign in through. One provider
  per token: homes that require two different providers take two tokens.
- **At each request**, `signed_in_providers` gives a token its recorded provider, and the
  usual check opens a home that requires it or requires nothing. If an owner sets
  another provider, the token stops opening the home (`403`, `sso_required`); if the
  requirement is lifted, it opens it as any token. A token without a recorded provider
  opens no home that requires one, as before: a requirement set after its creation cuts
  it.
- Everything else of ADR 0007 is unchanged: the token opens only its homes, keeps at
  most the role of the person, and stops with a disabled account, a membership removed,
  its expiry or its revocation.

**Why it is safe.** The token inherits a proof of sign-in through the provider made at
its creation, by the person, in a session that could open the home anyway; it is shown
once and only its digest is kept. Nothing the client sends decides it. A token that
could mint tokens would extend that proof, so tokens still cannot manage tokens.

## Consequences

- An integration such as Home Assistant can use a home that requires a provider, with a
  token created by a member signed in through it.
- **Limit.** HouseCairn sees a sign-in at the provider only when one happens. An account
  disabled at the provider keeps its tokens working until they expire or are revoked,
  as a session already open keeps the home (ADR 0021). That is why a token has no
  "never" lifetime (30, 90 or 365 days): the proof it carries is at most that old.
  Disabling the account in HouseCairn, or removing the member, cuts the token at once.
- A token bound to a home that requires no provider records none, even from a session
  through a provider: the rule set later cuts it, as the owner who sets it expects.
- Changing the required provider of a home cuts the tokens of the old one; the members
  create new ones from a session through the new provider.
