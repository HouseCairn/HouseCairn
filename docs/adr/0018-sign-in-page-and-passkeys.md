# 0018. Sign-in page: passkeys without a button, one button per provider

- Status: accepted
- Date: 2026-11-07
- Extends: [0007](0007-authentication-and-api-tokens.md)

## Context

The sign-in page listed a passkey button, a separator, a code-by-e-mail button and
a list of third-party providers under a heading. The maintainer found it
cluttered. The target is the form, then at most one button per configured identity
provider.

## Decision

**Passkeys have no button.** The address field carries `autocomplete="username
webauthn"` (set by `accounts.forms.LoginForm`, which extends allauth's form when
`MFA_PASSKEY_LOGIN_ENABLED` is on). Browsers that support *conditional mediation*
list the passkeys saved for the site in that field's suggestions; picking one
signs the person in, with no extra click.

What allauth 65 provides and is reused: the endpoint that issues the challenge
(a GET asking for JSON on `mfa_login_webauthn`, with no user, so discoverable
credentials), the endpoint that checks the signed answer (a POST of the form),
`mfa/js/webauthn-json.js` to convert between the browser API and JSON, and the
passkey login itself. allauth's own `login` script only binds a button and has no
conditional mode, so a small script, `static/js/passkey-login.js` (about 100
lines, served locally, no inline code), starts the conditional request. The
labels it needs are `data-` attributes of a hidden form rendered by
`account/snippets/passkey_login.html`.

**Fallback.** Where the browser has no conditional mediation but supports WebAuthn
(`PublicKeyCredential` exists), a "Use a passkey" button appears under the address
field as soon as something is typed in it. It starts the same request in modal
mode (the browser's own picker).

**The fallback does not depend on the address.** The card behind this decision
suggested offering the passkey only when the typed address has one. That needs an
endpoint answering "does this account have a passkey?", which tells anyone which
addresses are registered. The offer is shown for any non-empty address instead,
and the request is discoverable, so the server learns nothing.

**Failure is quiet.** A refused or cancelled conditional request (nobody asked for
it) leaves the password form as it is; only a click on the fallback button shows an
error message.

**Typing a password** cancels the pending conditional request (`AbortController`).

**Third-party sign-in.** `socialaccount/snippets/login.html` is overridden: no
separator, no heading, one secondary button per configured provider, labelled with
the provider's name (`OIDC_PROVIDER_NAME`, for example "Zitadel"), under the form.
The refusal page for closed OIDC sign-up is unchanged ([0007](0007-authentication-and-api-tokens.md)).

**Sign-up.** The link ("No account yet?") exists only when local sign-up is open,
as before. The "send me a sign-in code" button only appears if that allauth
feature is enabled, which it is not.

## Consequences

- Passkeys need an address field to autofill into; a person with a passkey and no
  password reaches it by tapping the field. Users who never tap it still see the
  password form and, in browsers without autofill support, the fallback button.
- The conditional request is created on every load of the page where passkey login
  is enabled; the cost is one small GET.
- Automated: the page has no passkey button, the field's attribute, the local
  scripts and the hidden form, the provider buttons (`tests/test_interface.py`),
  and, in CI, an end-to-end run in Chromium with a virtual authenticator that
  registers a passkey, then signs in through the conditional path and through the
  fallback button. Not automatable: the real autofill popup of each browser and
  platform (Safari and iCloud Keychain, Chrome and Google Password Manager,
  Firefox, Android, a hardware key). The checklist is in the pull request.
