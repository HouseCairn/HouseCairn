# Instance administration

The page of the administrator of the instance, at `/instance/`, reached from
**More** when your account is an administrator. Anyone else gets a 404, as if
the page did not exist.

You run the instance here and read no home: the page shows counts and
invitations, never a home, a member of a home, a task or a document (see
[Instance administrator](../administration/instance.md)).

- **Overview**: the number of accounts, whether open sign-up is on, whether
  outgoing email is configured and the sign-in providers the instance offers.
- **Invite someone to the instance**: an email address; the person receives a
  link that works once, creates their account and then their own home. The
  link goes by email only, so the form is hidden when the instance cannot send
  email. **Send again**
  makes a new link and a new expiry (the previous link stops working) and
  **Revoke** cancels it. Inviting answers the same whether or not the address
  already has an account.
- **Homes locked by a removed provider**: when the instance stops offering a
  sign-in provider that some homes require, nobody can open those homes.
  **Remove these requirements** clears the rule of every such home at once,
  without showing which they are.
- **Accounts** opens the administration site, where accounts are deactivated,
  deleted and made administrators (the address of an account and its password
  cannot be changed there, and no account is created there). Deleting an account follows
  the rules of erasure: the only administrator, and the only owner of a home
  with other members, cannot be deleted.
- **Audit log**: administration actions, invitations to the instance, accounts
  created or erased, homes unlocked, homes deleted (without the name), each
  with who did it and when. It holds nothing about the inside of a home.
