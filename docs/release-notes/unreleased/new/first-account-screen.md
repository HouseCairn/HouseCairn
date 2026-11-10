---
orphan: true
nosearch: true
---

- **First administrator on a web screen.** While an instance has no administrator,
  HouseCairn writes a one-time code in its log at each start. The
  [first-account screen](../../../screens/first-account.md) (`/setup/`) takes that code, a
  name, an address and a password, creates the administrator and signs them in, without
  a command on the server. The code is random, works once and expires after one hour;
  the screen answers 404 as soon as an administrator exists, or when
  `HOUSECAIRN_SETUP_SCREEN=false`. Single sign-on and `createsuperuser` work as before; the
  first one to create an administrator closes the others. See
  [First start](../../../getting-started/first-start.md).
