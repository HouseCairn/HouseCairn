# Profile

How you are named to the other members of your homes, at `/me/profile/` (**More**, then
**Profile**). One optional field:

- **Display name**: up to 60 characters, on one line. It is what people see on the tasks you
  are in charge of, in the [history](history.md), in [Today](today.md) and in the
  [household](household.md).

Without a display name you are shown by your full name if you have one, and otherwise by the
part of your email address before the `@`. Your whole address is never used to name you on
those screens; it appears only where the address is the subject (your account, an
invitation, the sheet of a member).

The same field is in the [API](../api/index.md): `GET` and `PATCH /api/v1/me/`.
