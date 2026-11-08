# Settings

Most of what an administrator configures can be set **in the interface** and by an
**environment variable**, as a pair. The variable wins; without it, the value chosen in
the interface is used; without either, the default. The screen is
**Instance administration, Settings** (see [Instance settings](../screens/instance-settings.md)).

1. **A variable is set** (and not empty): it decides. In the interface the field is locked,
   shows the value in force and names the variable. The interface and the API refuse to
   change it.
2. **No variable**: an administrator changes the value in the interface or the API. It is
   stored in the database, with the default shown next to it and a button to restore
   the default.
3. **Nothing set**: the default.

An instance configured only with variables, as before, behaves the same: every field is
locked. A variable set to an empty value counts as not set, so a Compose file that passes
`EMAIL_HOST=${EMAIL_HOST:-}` leaves the field editable.

## The table

```{note}
Every change takes effect at once on the process that saves it, and within a few seconds on
the others (each process reloads the stored values every five seconds). The mail server, the
sender, the sign-up rules, the invitation lifetime and the public address need no restart.
```

% settings-table:start
| Setting | Variable | Section | Default | Takes effect |
| --- | --- | --- | --- | --- |
| Public address | `HOUSECAIRN_SITE_URL` | Public address | (none) | At once |
| Open sign-up | `HOUSECAIRN_SIGNUP_OPEN` | Sign-up | `false` | At once |
| Sign-up through single sign-on | `HOUSECAIRN_OIDC_SIGNUP` | Sign-up | `closed` | At once |
| Allowed domains | `HOUSECAIRN_SIGNUP_ALLOWED_DOMAINS` | Sign-up | (none) | At once |
| Blocked domains | `HOUSECAIRN_SIGNUP_BLOCKED_DOMAINS` | Sign-up | (none) | At once |
| Anti-robot work | `HOUSECAIRN_SIGNUP_POW_BITS` | Sign-up | `16` | At once |
| Invitation lifetime (days) | `HOUSECAIRN_INVITATION_LIFETIME_DAYS` | Invitations | `7` | At once |
| SMTP server | `EMAIL_HOST` | Outgoing email | (none) | At once |
| SMTP port | `EMAIL_PORT` | Outgoing email | `587` | At once |
| STARTTLS | `EMAIL_USE_TLS` | Outgoing email | `true` | At once |
| TLS from the first byte | `EMAIL_USE_SSL` | Outgoing email | `false` | At once |
| SMTP user name | `EMAIL_HOST_USER` | Outgoing email | (none) | At once |
| SMTP password | `EMAIL_HOST_PASSWORD` | Outgoing email | (none) | At once |
| SMTP timeout (seconds) | `EMAIL_TIMEOUT` | Outgoing email | `15` | At once |
| Sender address | `DEFAULT_FROM_EMAIL` | Outgoing email | `HouseCairn <noreply@localhost>` | At once |
% settings-table:end

`manage.py check --deploy` reads the variables and the defaults, not the database: a setting
chosen in the interface is checked when it is saved, not at start-up.

The list of settings is the same one the API returns
(`GET /api/v1/instance/settings/`, with the variable, the default and the source of each).

## Secrets

The SMTP password is write-only. The interface and the API say whether one is set, never
what it is; it is absent from the audit log, the exports and the logs. A secret stored
from the interface is encrypted in the database with a key derived from the instance's
`SECRET_KEY`. If `SECRET_KEY` changes, the stored secret can no longer be read: the instance
treats it as not set, the screen says so, and you enter it again. To rotate the key
without losing it, list the old key in Django's `SECRET_KEY_FALLBACKS` while you re-enter
the secrets. A password set by `EMAIL_HOST_PASSWORD` is shown as "set", without its value.

## What changing a setting asks for

- You must be an instance administrator, and signed in recently (five minutes): the
  interface sends you to confirm your sign-in, and the API answers `403` with the code
  `reauthentication_required`. An API token never serves these endpoints.
- A value that is not valid is refused with a message. Open sign-up is refused while no
  mail server is set. The **Test the connection** button opens a connection to the mail
  server and closes it; it is never required to save.
- Each change is written to the instance's [audit log](../screens/instance.md) with who
  made it, the setting and the old and new values; for a secret, only that it changed.

## Server variables: environment only

These cannot be changed in the interface: the instance needs them before it has a
database, or a mistake could lock the administrator out. The **Server** part of the
screen shows them read-only, without secrets.

| Variable | Why it stays in the environment |
| --- | --- |
| `SECRET_KEY` | Signs sessions and encrypts stored secrets. |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | A wrong value makes the instance unreachable. |
| `DATABASE_URL`, `HOUSECAIRN_DATA_DIR` | Needed before the settings can be read. |
| `HOUSECAIRN_BEHIND_TLS_PROXY`, `HOUSECAIRN_FORWARDED_ALLOW_IPS` | Decide which proxy headers to trust. |
| `DEBUG` | Changes the security posture of the whole instance. |
| `HOUSECAIRN_TASK_WORKERS`, `HOUSECAIRN_WEB_WORKERS` | Fixed when the processes start. |
| `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL` | Decides who may become the first administrator. |

Single sign-on providers (`OIDC_*`), the rate limits, the default language and time zone and the
name of the instance are not in the interface yet: they stay variables, see
[Environment variables](variables.md).
