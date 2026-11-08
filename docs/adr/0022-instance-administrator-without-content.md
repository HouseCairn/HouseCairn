# 0022. Instance administrator without access to content

- Status: accepted
- Date: 2026-11-08

## Context

The public instance is run by one person for many households. That person
becomes the controller of other people's data (GDPR) and should hold as little
of it as the work allows: the administrator keeps the instance running, not the
homes. The administration site of Django, which lists every model of every
app, was the way around the isolation of ADR 0006: it listed homes and
memberships.

## Decision

- **Who.** The administrator is an active account that is `is_staff` and
  `is_superuser` (`accounts.services.is_instance_admin`). It is a role on the
  instance, not a membership: being one adds no home to `homes_for`, so the
  web, the API and tokens answer 404 for every home of which the account is
  not a member, as for anyone else.
- **What the administrator does.** Accounts (administration site: create,
  deactivate, delete, administrators), invitations to the instance
  (`/instance/`, `/api/v1/instance/invitations/`), the audit log of the instance
  (ADR 0023), the providers and settings (environment variables), and one
  action on homes that reads none: clearing the sign-in rule of homes whose
  provider was removed (`/instance/unlock/`), which returns a count.
- **What the administrator does not do.** Read a home, its members, invitations,
  events, files or audit log; export or delete a home; be told a home's name.
- **The administration site shows no home.** Nothing from `homes` or `events`
  is registered, and `tests/test_instance_admin.py` fails if any model that
  belongs to a home is. The API token page hides the homes of a token and
  cannot delete it (revoking is enough); the page that confirms the deletion
  of an account lists the account only, since Django would list its
  memberships, and with them the names of homes.
- **No token.** The instance endpoints, like the screens that erase an account
  or a home, need a person signed in: an API token, even one owned by an
  administrator, gets 403.
- **Erasing accounts keeps the rules.** An administrator deletes an account
  through the same service as the person (ADR 0023): the last administrator,
  and the only owner of a home that others belong to, cannot be erased, with a
  message that names no home.

## Consequences

- An administrator who needs to see a home must be invited to it by an owner,
  like anyone.
- A model added later that belongs to a home stays out of the administration
  site by the test, not by memory.
- Django's `is_superuser` still grants every permission of the administration
  site: the guarantee is that no home model is registered there, not a
  permission system. The database and its backups remain readable by whoever
  operates the machine; that is outside the application's reach and is said in
  the administration documentation.
