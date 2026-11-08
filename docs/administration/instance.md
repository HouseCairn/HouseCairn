# Instance administrator

The administrator runs the instance: accounts, invitations, sign-in providers
and settings. The administrator **does not read the homes**
([ADR 0022](../adr/0022-instance-administrator-without-content.md)).

## Who is an administrator

An active account that is both *staff* and *superuser*. The first account of a
new instance created through single sign-on is one (see
[Single sign-on](oidc.md)); `manage.py createsuperuser` makes another; the
administration site (`/admin/`) grants or withdraws the role on an existing
account (both boxes, audited). Being an administrator adds no home to the
account: it sees the homes it belongs to, like anyone.

## What the administrator can do

- **Accounts**, in the administration site: switch an account on or off, grant
  or withdraw the administrator role, delete an account. Changes and deletions
  are written to the audit log of the instance. An account is created by an
  invitation to the instance (or by sign-up, or single sign-on, when the
  instance allows it), never from the administration site.
- **Invitations to the instance**, at `/instance/` and in the API
  (`/api/v1/instance/invitations/`): an address receives a link by email,
  creates an account and then their own home. They need outgoing email. See
  [Instance administration](../screens/instance.md).
- **Providers and settings**: environment variables (see
  [Environment variables](variables.md)). Nothing is edited in the interface.
- **Unlocking homes**: when a provider is removed from the configuration, the
  homes that required it stay locked. **Remove these requirements** on the
  instance page (or `POST /api/v1/instance/unlock/`) clears the rule of all of
  them, without showing which. An owner can also lift the rule of their own
  home from its locked page.
- **Audit log of the instance**: `/instance/audit/` and
  `/api/v1/instance/audit/`.

## What the administrator cannot do

Read a home, its members, invitations, events, files or audit log; export or
delete a home; be given the name of a home. The web pages and the API answer
404 for a home the administrator does not belong to, the administration site
registers no home model, and an API token never serves the administrator's
endpoints.

- The page of an account in the administration site does not list its
  memberships, and deleting an account does not either.
- The administrator deletes an account by the same rules as the person: the
  only administrator, and the only owner of a home with other members, cannot be
  erased.
- The administrator cannot take over an account. The administration site has no
  page to set a password, shows the address of an account read-only, cannot add
  an account, and registers no model that holds a credential: email addresses,
  linked identities and provider keys, authenticator secrets and recovery
  codes, scheduled and finished background tasks. API tokens are listed and
  revoked, never read. A person who lost their access recovers it with the
  *Forgot your password?* link, which they trigger and which goes to their own
  address; the administrator can neither do it for them nor read the link.
  Without outgoing email there is no such link, and the operator of the machine
  sets a new password with `manage.py changepassword`.

## What this does not protect against

Whoever operates the machine reads the database and its backups, and can run
`manage.py` (`changepassword`, `shell`): the guarantee is about the application,
not about the host. Say so to the people
who sign up (privacy policy, backups, who has access to the server).
