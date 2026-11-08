# Member

One person of the household, at `/h/<home id>/household/members/<id>/`: their
address, their role and since when they belong to the home.

An owner can change the role, remove the person from the home, or **make them
owner**: they become owner and you become a member, in one step. On your own
page, **Leave this home** removes you from it; the last owner cannot leave.
Removing someone and leaving both ask you to confirm on a page of their own
first. You can leave a home that requires a sign-in provider without signing
in through it.

Removing someone takes effect at once: their next request no longer sees the
home, and their API tokens lose it too.
