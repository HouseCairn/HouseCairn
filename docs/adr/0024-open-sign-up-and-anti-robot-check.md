# 0024. Open sign-up and its anti-robot check

- Status: accepted
- Date: 2026-11-08

## Context

Sign-up is closed by default: the instance is entered by invitation (ADR 0020).
An operator may open it. Then robots will come, and the instance must not need
a third-party service to resist them (no external resource, ADR 0011; privacy
first). The specification asks for verification of the address, a rate limit,
an anti-robot check without a third party, and optional domain lists.

## Decision

- **Verification of the address is mandatory** when sign-up is open
  (`ACCOUNT_EMAIL_VERIFICATION` defaults to `mandatory` with
  `HOUSECAIRN_SIGNUP_OPEN`): the account cannot sign in before its address is
  confirmed by email. Open sign-up without outgoing email is an error of
  `manage.py check` (`housecairn.E001`) and the instance does not start.
- **No enumeration.** django-allauth's `ACCOUNT_PREVENT_ENUMERATION` stays on:
  signing up with an address that has an account gives the same answer as a new
  address, and the existing account is told by email. Password reset, and
  inviting, answer alike (tests).
- **Proof of work** (`accounts.antibot`), chosen over a locally generated
  question: a question (arithmetic, a word) is solved by any script and is
  unpleasant for people; a proof of work costs a robot computation for every
  account and needs nothing from the person. The page carries a random
  challenge kept in the visitor's session; a script (`static/js/pow.js`, no
  inline code) finds `n` such that SHA-256 of `challenge:n` begins with
  `HOUSECAIRN_SIGNUP_POW_BITS` zero bits (16 by default, about a second;
  8 to 24); the server checks it with one hash. The challenge leaves the
  session when checked, so a solution works once and only for the session that
  was given the challenge; it expires after 30 minutes; a refused form comes
  back with a new one. The submit button waits for the script; without
  JavaScript or a secure context (SubtleCrypto needs HTTPS or localhost) the
  page says so and the account cannot be created.
- **Rate limit** of the sign-up page per client address (`10/m/ip,60/d/ip`),
  and the limits of ADR 0025.
- **Domain lists.** `HOUSECAIRN_SIGNUP_ALLOWED_DOMAINS` (only these, subdomains
  included) and `HOUSECAIRN_SIGNUP_BLOCKED_DOMAINS` apply to the sign-up form and
  to open sign-up through OIDC; never to invited people or to accounts the
  administrator creates.

## Consequences

- A proof of work makes bulk sign-up cost something; it does not stop a
  determined attacker with computing power. The barriers that count are the
  verified address, the rate limit and the lists. If abuse comes, the next step
  is raising the difficulty or closing sign-up, not a third-party service.
- A visitor on a very slow device waits a few seconds; the difficulty is a
  setting.
- Disposable-address services are not listed in the code; operators who need
  that use the blocked list.
