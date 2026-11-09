# Audit log of a home

Who did what in a home, at `/h/<home id>/audit/`. Only owners see it, from the
**Audit log** tab of the home. Each line gives the operation, who did it and
when:

- rooms, items and tasks added, changed or deleted;
- stock articles and suppliers added, changed or deleted (movements and the stock taken
  when a task is done are in the ledger of the article, not here);
- photos of a room or an item, and files of a task, added or deleted;
- roles changed, members removed or leaving, ownership transferred;
- invitations sent, sent again, revoked or accepted, with the role, never the
  address;
- the sign-in rule set or removed, with the provider;
- the home exported.

What an entry concerns is named by its title only: the name of the room or of the
item, the title of the task, the room or item a photo belongs to, the task a file is
attached to. An entry that changes something lists the names of the fields that
changed, never their values. The log holds no note, cost, procedure or file, nor
the name of a file. Until something is done in the home, the page says what will
appear. It is deleted with the home.
The administrator of the instance does not see it: the log of the instance is
another one, about accounts and invitations to the instance.
