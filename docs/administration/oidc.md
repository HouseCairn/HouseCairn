# Single sign-on (OpenID Connect)

HouseCairn signs people in through any OpenID Connect provider; none is named
in the code. Single sign-on is off until `OIDC_SERVER_URL` is set
([ADR 0007](../adr/0007-authentication-and-api-tokens.md)).

1. At the provider, create a client (an application) of the web type, with
   the authorization code flow and this redirect URI, for an instance at
   `housecairn.example.com`:

   ```text
   https://housecairn.example.com/accounts/oidc/oidc/login/callback/
   ```

   The second `oidc` is `OIDC_PROVIDER_ID`, `oidc` by default.
2. In `deploy/production.env`:

   ```ini
   OIDC_SERVER_URL=https://id.example.com
   OIDC_CLIENT_ID=housecairn
   OIDC_CLIENT_SECRET=<secret given by the provider>
   HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL=admin@example.com
   ```

   `OIDC_SERVER_URL` is the issuer: HouseCairn reads
   `/.well-known/openid-configuration` below it. `OIDC_PROVIDER_NAME` is the
   provider's name, for example `Company SSO` (`Single sign-on` by default);
   the sign-in page shows one button per provider, under the form, labelled
   "Continue with" and that name. A click on it goes straight to the
   provider, with no intermediate confirmation page.
3. Restart the container, then sign in right away with the address set in
   `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL`, which the provider must have verified.

## Who gets an account

- **First sign-in of a new instance**: while the instance has never had an
  account, the first identity to sign in becomes its administrator; with
  `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL`, only that verified address can.
- **Afterwards**, with `HOUSECAIRN_OIDC_SIGNUP=closed` (the default), an
  identity without an account is refused, with a page that asks to contact the
  administrator. With `open`, anyone the provider accepts gets an account,
  without administration rights.
- **Invited addresses**: an identity whose address has a pending invitation to
  a home gets an account, without administration rights, if the provider
  asserts the address as verified (`email_verified` is `true`).
- An existing local account is never taken over by an identity that only
  shares its address: sign in with the local account, then link the identity
  from the account pages.

## Requiring single sign-on for a home

Providers are declared by the administrator of the instance only, with the
variables above. Single sign-on is never required for the whole instance: the
built-in sign-in (password, passkey, second factor) stays the default.

An owner can require that the members of one home sign in through a declared
provider, from **Household and roles**. The rule is checked each time the home
is opened, by the web and by the API:

- a session signed in with a password or a passkey sees the home in its list,
  marked, and gets a page that offers to continue with the provider;
- the API answers `403` with `"code": "sso_required"` and the provider's
  identifier;
- API tokens never open such a home, since a token is not a sign-in through
  the provider.

A member whose account is not yet linked to the provider links it from the
account pages, signed in, then signs in through the provider. If a provider is
removed from the instance, the homes that require it stay locked until the
rule is lifted. An owner opens the locked page and chooses **Remove the
sign-in requirement** (it is offered only when the provider is no longer
declared); or the administrator uses **Remove these requirements** on the
[instance page](../screens/instance.md), which clears them all without showing
any home. Leaving a locked home never needs the provider.
