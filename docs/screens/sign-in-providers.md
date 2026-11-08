# Sign-in providers

The OpenID Connect providers of the instance, at `/instance/providers/`, reached from
**Instance administration**. Administrators only; anyone else gets a 404.

- **Set by variables**: the provider of the `OIDC_*` variables, read only, with its issuer,
  client identifier, whether a client secret is set, and the number of linked accounts.
- **Declared here**: one row per provider, enabled or disabled, with its identifier and the
  number of linked accounts. A row opens the provider.
- **Add a provider**: identifier, name, issuer, client identifier, client secret, PKCE and
  Enabled. The redirect URI to register at the provider is shown below the fields.

The page of a provider shows its redirect URI, whether a client secret is stored, the
accounts linked to it and the homes that require it, then the same fields without the
identifier, which never changes. Leave the client secret empty to keep the stored one; a new
issuer clears it unless you enter it again in the same change.
**Test the issuer** checks the issuer typed in the field and saves nothing. **Delete** is
refused while a home requires the provider; disable it instead.

Saving or deleting asks you to have signed in within the last five minutes. You cannot
disable or delete your own last way to sign in, nor change its issuer, client identifier or
secret. See [Single sign-on](../administration/oidc.md).
