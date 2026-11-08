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

## Declaring providers in the interface

An administrator can also declare providers on **Instance administration, Sign-in
providers** (see [Sign-in providers](../screens/sign-in-providers.md)), or with the API
(`/api/v1/instance/providers/`), without a restart. A provider set by the variables above
is listed there read only; change it in the variables.

Each provider of the interface has:

- an **identifier**, such as `company`, chosen once: it is in the redirect URI to register
  at the provider, `https://housecairn.example.com/accounts/oidc/company/login/callback/`.
  It never changes and is never given to another provider, even after deletion;
- a **name**, on the button: "Continue with" and the name, such as `Company SSO`;
- the **issuer**, an `https://` address, the client identifier and the client secret (write
  only, encrypted in the database);
- **PKCE**, on by default, and **Enabled**, off by default: declare the provider, test it,
  then enable it.

**Test the issuer** reads the issuer's OpenID configuration and says whether it is valid; it
is never required to save. The instance calls only `https://` addresses for it, never its
own address nor a link-local one, and follows no redirect.

Rules that protect accounts and homes:

- Once accounts are linked to a provider, its **issuer cannot change**: another issuer
  could sign in as them. Declare a new provider for the new issuer.
- A new **issuer clears the client secret**, unless you enter the secret again in the same
  change: at sign-in the secret is sent to the issuer, and it must not reach another one.
  An enabled provider is never left without a secret: a new issuer for it is refused unless
  you enter the secret again, or untick **Enabled**, in the same change. A new client
  identifier alone keeps the secret.
- A provider that **a home requires cannot be deleted**. Disable it: the homes then follow
  the way out described below.
- You cannot disable or delete **your last way to sign in**, nor change its issuer, client
  identifier or secret: set a password or a passkey, or link another provider, first. This
  protects only you: check the linked accounts of a provider before you change it. In the
  administration site, the **only administrator** cannot be switched off nor lose the
  administrator role.

Each change is in the instance audit log; the client secret never is.

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
variables above or in the interface. Single sign-on is never required for the whole instance: the
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
