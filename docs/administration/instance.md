# Instance administrator

The administrator runs the instance: accounts, invitations, sign-in providers
and settings. The administrator **does not read the homes**
([ADR 0022](../adr/0022-instance-administrator-without-content.md)).

## Who is an administrator

An active account that is both *staff* and *superuser*. The first account of a
new instance created through single sign-on is one (see
[Single sign-on](oidc.md)); `manage.py createsuperuser` makes another; the
administration site (`/admin/`) sets the two boxes on an account. Being an
administrator adds no home to the account: it sees the homes it belongs to,
like anyone.

## What the administrator can do

- **Accounts**, in the administration site: create, deactivate, delete,
  administrators. Changes and deletions are written to the audit log of the
  instance.
- **Invitations to the instance**, at `/instance/` and in the API
  (`/api/v1/instance/invitations/`): an address receives a link by email,
  creates an account and then their own home. They need outgoing email; without
  it, create the account in the administration site. See
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

## What this does not protect against

Whoever operates the machine reads the database and its backups: the
guarantee is about the application, not about the host. Say so to the people
who sign up (privacy policy, backups, who has access to the server).
