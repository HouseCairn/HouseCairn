# First account

The page that creates the first administrator of a new instance, at `/setup/`. It
exists only while the instance has no administrator and `HOUSECAIRN_SETUP_SCREEN` is not
`false`; otherwise the address answers 404. The sign-in page links to it while it is open.

HouseCairn writes a **setup code** in its log at each start (see
[First start](../getting-started/first-start.md)). The code is random, works once and
expires after one hour.

- **Setup code**: as written in the log; case, spaces and hyphens do not matter. A code
  that is wrong, expired or already used gets the same answer, and the page never writes
  the code back.
- **Your name**: how the members of your homes will see you.
- **Email address** and **Password**, twice: the rules for passwords are those of every
  account.

**Create the administrator** creates the account, uses the code up, signs you in and opens
the administration of the instance. The creation is in the audit log of the instance,
without the code. A code that was refused because of the address or the password stays
usable until it expires.

The page is limited per client address: after a few tries in a minute it answers “Too
many requests”.
