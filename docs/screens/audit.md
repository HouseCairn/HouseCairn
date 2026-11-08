# Audit log of a home

Who changed what in a home, at `/h/<home id>/audit/`. Only owners see it,
from **Household and roles**. Each line gives the operation, who did it and
when:

- roles changed, members removed or leaving, ownership transferred;
- invitations sent, sent again, revoked or accepted, with the role, never the
  address;
- the sign-in rule set or removed, with the provider;
- the home exported.

The log holds no task, project, document or note. It is deleted with the home.
The administrator of the instance does not see it: the log of the instance is
another one, about accounts and invitations to the instance.
