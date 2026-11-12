# Demonstration instance

A demonstration instance lets anyone try HouseCairn without installing it: two accounts
whose address and password are public, a fictional home, and everything back to that state
every night. It is the instance at <https://demo.housecairn.app>.

```{warning}
`HOUSECAIRN_DEMO=true` erases **every** account, home and file of the instance every night.
Never set it on an instance that holds real data.
```

## Turn it on

Set `HOUSECAIRN_DEMO=true` on a new, empty instance (with Coolify, in the environment
variables of the application), then start it. At the first start, on an instance without
any account, HouseCairn creates:

| Account | Address | Password |
| --- | --- | --- |
| Administrator of the instance, owner of the home | `admin@example.com` | `housecairn-demo` |
| User, member of the home (read and write) | `user@example.com` | `housecairn-demo` |

and the fictional home of `load_demo_data`, in the default language of the instance
(`HOUSECAIRN_DEFAULT_LANGUAGE`, `en` or `fr`). The addresses are in `example.com`, a domain
reserved for examples: no mail is ever delivered there.

## Every night

At 03:00, Paris time (Europe/Paris, whatever the time zone of the instance), the task worker
runs `reset_demo`: it erases the accounts, the homes and what they hold, the settings saved in
the interface, the sessions, the audit log and the uploaded files, then creates the two
accounts and the home again. The dates of the home are relative to that day, so that Today
always has something overdue, due and coming.

To reset by hand: `docker compose exec housecairn python -m housecairn.entrypoint manage reset_demo`. The command
refuses to run while `HOUSECAIRN_DEMO` is not true.

## What changes on a demonstration instance

- **Settings read only.** The administrator sees the settings and the sign-in providers of the
  instance, but cannot change them, on the screen or through the API (a `403` with the code
  `demo`).
- **Nothing sent.** No email, no notification (a channel can be added, not tested), no preview
  of a link, no sign-in through a provider: the instance makes no outgoing connection.
  Invitations are by link only.
- **Accounts kept.** No account can be created: sign-up and the first-account screen are
  closed. The two public accounts keep their password, their address, their rights and their
  existence; no second factor can be added to them.
- **Small files.** 2 MB per file, 20 MB and 50 files per home, 200 MB for the whole instance.
- **A banner** on every page says that the instance is a demonstration, that what is entered
  is public and when it is reset; the sign-in screen gives the two accounts.

The reasons and the limits are in [ADR 0071](../adr/0071-demonstration-instance.md).
