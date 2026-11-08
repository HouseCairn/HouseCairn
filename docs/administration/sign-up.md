# Open sign-up

By default nobody can create an account: people come in by invitation, from an
owner of a home or from the administrator of the instance. You may open
sign-up to everyone with `HOUSECAIRN_SIGNUP_OPEN=true`
([ADR 0024](../adr/0024-open-sign-up-and-anti-robot-check.md)). Do it once the
instance is run in earnest: open sign-up invites robots.

## What opening sign-up needs

- **Outgoing email.** Each address is verified by email before the account
  can sign in (`ACCOUNT_EMAIL_VERIFICATION` is `mandatory` then). Without
  `EMAIL_HOST`, the instance refuses to start (`housecairn.E001`). See
  [Email](email.md).
- **HTTPS**, for the anti-robot check below to run in the browser.

## What protects it

- **Proof of work.** The sign-up page asks the browser for a small computation
  while the form is filled in, and the button waits for it. It costs a robot
  work for each account and needs nothing from the person, and no third-party
  service. `HOUSECAIRN_SIGNUP_POW_BITS` sets the work: `16` (the default) takes a
  second or a few, `8` to `24` are accepted, each bit doubling it. A challenge
  works once, for the visitor it was given to, for 30 minutes. It needs
  JavaScript and a secure connection: the page says so otherwise.
- **Rate limit**: the sign-up page answers 429 beyond 10 attempts a minute
  and 60 a day from one client address. See [Rate limits](rate-limits.md).
- **Domains.** `HOUSECAIRN_SIGNUP_ALLOWED_DOMAINS` (comma-separated: only these
  domains, subdomains included) and `HOUSECAIRN_SIGNUP_BLOCKED_DOMAINS` (never
  these). Neither list applies to people who are invited, nor to accounts the
  administrator creates. They apply to open sign-up through single sign-on too
  (`HOUSECAIRN_OIDC_SIGNUP=open`).
- **No enumeration.** Signing up with an address that already has an account
  answers exactly as for a new address, and the existing account is told by
  email. Password reset answers alike.

None of this stops an attacker with computing power and many addresses; they
make bulk sign-up cost something. If abuse comes, close sign-up and invite.
