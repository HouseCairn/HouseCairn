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
   "Continue with" and that name.
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
- An existing local account is never taken over by an identity that only
  shares its address: sign in with the local account, then link the identity
  from the account pages.
