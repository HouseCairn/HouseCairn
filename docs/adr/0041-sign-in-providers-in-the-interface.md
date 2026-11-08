# 0041. Sign-in providers declared in the interface, and the last way to sign in

- Status: accepted
- Date: 2026-11-08

## Context

ADR 0021 keeps the declaration of single sign-on providers to the instance administrator,
and until now that meant the `OIDC_*` variables only. ADR 0035 pairs administration with
environment variables: what a variable sets is locked, the rest can be changed in the
interface. A provider is a record (name, issuer, client, secret), not a single value, and
it carries more risk than a setting: identities are linked to it, homes can require it, and
a provider that asserts a subject can sign in as the account linked to that subject.

## Decision

**Providers of the interface live in their own table, `OidcProvider`**, not in
django-allauth's `SocialApp`, whose secrets are stored in clear. `SocialAccountAdapter.list_apps`
adds the enabled ones, built in memory, to those of the variables, at each call: a change
applies at once, in every process, with no restart. Each one has a display name, an issuer,
a client identifier, a client secret, PKCE (on by default) and an enabled flag (off by
default: declare, test, then enable).

**The provider set by the variables stays read only** (the pairing rule): the screen lists it
with its values and the secret as "set", the API answers `409 locked_by_environment` to a
change. Its identifier cannot be taken by a provider of the interface; if variables later declare
an identifier that the interface already has, the variables win and the other is not offered.

**The identifier never changes and is never reused.** It is the `provider_id` django-allauth
puts in the redirect URI, in every linked identity (`SocialAccount.provider`) and in the rule
of a home that requires the provider (`Home.required_provider`). Renaming a provider changes
only its display name, so the homes keep their link. A new provider cannot take an
identifier that a provider had (deletion only marks the row deleted), that an identity is
linked to, or that a home still requires: none of those links may pass to another provider.

**The issuer cannot change once identities are linked.** Another issuer could assert the
subject of one of them and sign in as its account. To move to another issuer, the
administrator declares a new provider, and each person links it. As before, no identity
reaches an account through a matching address (`SOCIALACCOUNT_EMAIL_AUTHENTICATION` and its
auto-connect stay off).

**The client secret stays with its issuer.** At sign-in, django-allauth reads the issuer's
OpenID configuration and sends the client identifier and secret to the token endpoint it
names. Were the secret kept across a change of issuer, an administrator who never saw it
could point a provider without linked accounts at a host of their own, enable it, start a
sign-in and receive the secret: write only would mean nothing. So a change of issuer clears
the stored secret, unless the same request carries one (the form field, or `secret` in the
API), and the audit log says "client secret cleared", without any value. An enabled provider
is not left without its secret: the change is refused, on the secret field, until the secret
is typed again or the provider is disabled in the same request. A refusal was chosen over
disabling the provider on the quiet: that would hide a sign-in button people use, and could
take away the last way to sign in of the administrator who acts. A provider without a secret
may still be enabled afterwards: a public client with PKCE needs none, and the client
identifier, which is not a secret, is then all the new issuer receives. A change of client
identifier alone keeps the secret: the secret still goes only to the token endpoint of the
same issuer, which issued it and already holds it. The issuer, not the client identifier,
decides where the secret is sent; a wrong pair only makes sign-in fail at the provider.

**A provider that a home requires cannot be deleted.** The refusal gives the number of homes
and none of their names (ADR 0022). Disabling it is allowed: the homes then follow the way out
of ADR 0021 (the owner removes the requirement, or the administrator clears every such rule
from the instance page). That keeps every lift of a requirement an explicit, audited action.

**The last way to sign in.** Disabling or deleting a provider is refused when the
administrator who does it would be left with no way to sign in: no usable password, no
passkey, and no identity linked to another provider that stays enabled (or to the provider of
the variables). Changing the issuer, the client identifier or the secret of an enabled
provider goes through the same check, since a wrong value breaks sign-in as surely as
disabling it; the name and PKCE do not. In the administration site, the only active
administrator cannot be switched off nor lose `is_staff` or `is_superuser`; erasing that
account was already refused (ADR 0023).

This guard protects the administrator who acts, and no one else. Known limits, accepted
without a further mechanism: another administrator, or a member who signs in only through
that provider, can lose their way to sign in when it is disabled, deleted or changed. The
screen of the provider shows how many accounts are linked to it, so the administrator sees
who depends on it before such a change.

**The client secret** is encrypted like the secrets of ADR 0035 (Fernet, key derived from
`SECRET_KEY`), write only, never in the screen, the API, the audit log (only "client secret
changed" or "client secret cleared"), the exports or the logs. A secret the key can no longer
read is shown as such and handed to django-allauth as empty, so that sign-in through that
provider fails until the administrator enters it again. Deleting a provider wipes its secret.

**Content Security Policy.** The browser applies `form-action` to the redirect that follows a
sign-in button. Each HTML response gets the origins (`https://host[:port]`) of the issuers of
the enabled providers, added by `SettingsSnapshotMiddleware`; never a wildcard, never a path.
The provider of the variables stays in the static policy. As for that one, an authorization
endpoint on another origin than its issuer is not covered: the browser then blocks the
redirect, and the screen's test does not detect it.

**The test button** reads `/.well-known/openid-configuration` below the issuer and checks that
it is JSON with `https://` endpoints and the same issuer. It is never required to save. Since
the server makes the request, it is kept narrow: instance administrators only (no member, no
API token), five tests a minute, `https://` only, the host resolved once and every address
checked, the connection made to the checked address (no second resolution, so no DNS
rebinding) with the certificate verified against the host name, no redirect followed, five
seconds and 64 KiB at most, and the answer is one of a few fixed sentences, never the body.
Loopback, link-local (cloud metadata services), multicast, unspecified and reserved addresses
are refused, at the test and, for an address typed as is, when the issuer is saved. Private
networks are allowed: an identity provider often runs on the local network.

**What stays outside this choice.** At sign-in, django-allauth fetches the same configuration
itself, as it does for the provider of the variables; the address checks of the test button do
not apply there. An administrator could therefore point an issuer, by host name, at an
internal `https://` service and have the instance request its `/.well-known/` path at sign-in.
That is accepted for an instance administrator, as ADR 0035 accepts the mail test.

## Consequences

- Every write needs a recent sign-in (ADR 0035), through the web or the API, and goes to the
  audit log: added, each changed field with its old and new values, client secret changed,
  client secret cleared, deleted.
- Moving an enabled provider to another issuer takes its secret in the same change; there is
  no way to keep the old secret for the new issuer.
- An administrator who signs in through one provider only must set a password or a passkey,
  or link another provider, before disabling it or changing its issuer, client identifier or
  secret (to rotate the secret, for instance).
- Moving a provider from the variables to the interface keeps its identifier only while the
  variables stay; once they are removed, its identities and the homes that require it keep
  the identifier reserved.
- The rate limits, quotas, default language and time zone, and the instance name listed for
  this part of the lot are not in this decision; they follow in a separate change.
