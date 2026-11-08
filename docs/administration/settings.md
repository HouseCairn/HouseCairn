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
the others (each process reloads the stored values every five seconds). No setting needs a
restart: the mail server, the sign-up rules, the rate limits, the quotas, the language, the
time zone and the name of the instance included.
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
| Name of the instance | `HOUSECAIRN_INSTANCE_NAME` | Name, language and time zone | `HouseCairn` | At once |
| Default language | `HOUSECAIRN_DEFAULT_LANGUAGE` | Name, language and time zone | `en` | At once |
| Time zone | `TIME_ZONE` | Name, language and time zone | `UTC` | At once |
| Sign-ins a minute | `HOUSECAIRN_RATELIMIT_LOGIN` | Rate limits | `30` | At once |
| Failed sign-ins in five minutes | `HOUSECAIRN_RATELIMIT_LOGIN_FAILURES` | Rate limits | `5` | At once |
| Sign-ups a minute | `HOUSECAIRN_RATELIMIT_SIGNUP` | Rate limits | `10` | At once |
| Sign-ups a day | `HOUSECAIRN_RATELIMIT_SIGNUP_DAY` | Rate limits | `60` | At once |
| Password reset requests a minute | `HOUSECAIRN_RATELIMIT_PASSWORD_RESET` | Rate limits | `20` | At once |
| Invitations sent a minute | `HOUSECAIRN_RATELIMIT_INVITATIONS` | Rate limits | `10` | At once |
| Invitations sent a day | `HOUSECAIRN_RATELIMIT_INVITATIONS_DAY` | Rate limits | `50` | At once |
| Invitation links opened a minute | `HOUSECAIRN_RATELIMIT_INVITATION_LINKS` | Rate limits | `30` | At once |
| Tests of the mail server or of an issuer a minute | `HOUSECAIRN_RATELIMIT_TESTS` | Rate limits | `5` | At once |
| Largest file (bytes) | `HOUSECAIRN_PHOTO_MAX_BYTES` | Files of a home | `10485760` | At once |
| Space for the files of a home (MB) | `HOUSECAIRN_HOME_STORAGE_MB` | Files of a home | `5120` | At once |
| Number of files of a home | `HOUSECAIRN_HOME_MAX_FILES` | Files of a home | `5000` | At once |
| Notifications | `HOUSECAIRN_NOTIFICATIONS_ENABLED` | Notifications | `false` | At once |
| Check for reminders every (minutes) | `HOUSECAIRN_NOTIFICATIONS_INTERVAL` | Notifications | `5` | At once |
% settings-table:end

The start-up checks (`manage.py check`, which `migrate` runs too) read the variables and the
defaults, with one exception: `housecairn.E001`, which stops the start when
`HOUSECAIRN_SIGNUP_OPEN` opens sign-up without a mail server, also counts a mail server chosen
in the interface. That is why the interface refuses to remove that server, or restore its
default, while sign-up is open. Otherwise a setting chosen in the interface is checked when it
is saved, not at start-up.

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
- An administrator who signs in through single sign-on only (no password, passkey or
  authenticator app in HouseCairn) has nothing to confirm a sign-in with: as in
  django-allauth, their session always counts as recent, and only the session rules of the
  identity provider apply. To have the five-minute rule, give that account a password or a
  passkey.
- A value that is not valid is refused with a message. Open sign-up is refused while no
  mail server is set, and so is removing the mail server, or restoring its default, while
  sign-up is open. The **Test the connection** button opens a connection to the mail
  server and closes it; it is never required to save.
- That button connects, from the instance's own network, to the server and port in force,
  which an administrator can set to any host, and tells apart a refused login, a failed TLS
  and no answer: an administrator can use it to probe a host and port. It is kept to
  instance administrators and limited to five tests a minute for each.
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

The **Server** part shows all of them except `HOUSECAIRN_WEB_WORKERS`: only the container's
start-up program reads it, to start that many web processes; the application itself does not.

The single sign-on provider of the `OIDC_*` variables stays a variable; others are declared in
the interface (see [Single sign-on](oidc.md)).

## Rate limits, quotas, language, time zone and name

- **Rate limits**: see [Rate limits](rate-limits.md). Each is a whole number within bounds:
  none can be set to 0 nor switched off, and a day cannot allow fewer than a minute.
- **Files of a home**: the largest file (in bytes, as `HOUSECAIRN_PHOTO_MAX_BYTES` always was),
  the space and the number of files each home may hold. They are measured on disk, thumbnails
  and deleted files included until they are purged, and checked by every way to add a photo,
  an attachment or a label, in the screens and the API. Over a quota, the upload is refused
  with a message that gives the numbers. **Instance administration, Files of the homes**
  shows what each home takes, by its identifier only (see
  [Files of the homes](../screens/instance-usage.md)).
- **Default language**: the language of people whose browser asks for none that the instance
  offers. The language a person's browser asks for always wins.
- **Time zone**: an IANA zone such as `Europe/Paris`. It decides what today is, and so which
  tasks are late, in the screens and in the background tasks alike.
- **Name of the instance**: in the app bar, the title of the pages and the emails, at most 64
  characters on one line. Empty, the product name is shown. See
  [ADR 0042](../adr/0042-rate-limits-quotas-language-and-instance-name.md).
