# 0035. Instance settings in the interface, paired with environment variables

- Status: accepted
- Date: 2026-11-08

## Context

Until now every setting came from an environment variable (ADR 0012). The maintainer's
decision: as much administration as possible must be possible in the interface **and** by
variable, as a pair. A variable that is set locks the field, and the value in force stays
visible. A deployment that uses only variables must behave exactly as before.

## Decision

**A setting is eligible when it can change while the instance runs and cannot lock the
administrator out.** The list is `housecairn.instance.registry.SETTINGS`: public address, open
sign-up, sign-up through single sign-on, allowed and blocked domains, anti-robot work,
invitation lifetime, and the outgoing email (server, port, STARTTLS, TLS, user, password,
timeout, sender). Providers, rate limits, quotas, language, time zone and the instance name
follow in the next part of this lot.

**Resolution order: variable, then database, then default.**

- A variable that is set and not empty wins. It is read once, when Django starts
  (`registry.read_environment`, called from `settings.py`, which is the only place
  these variables are read). Its field is locked, and the interface and the API refuse
  to change it (a 409 in the API). An invalid variable stops the start-up, as before.
- Otherwise the value stored in `SettingValue` (one row per setting that differs from its
  default; setting a value equal to the default deletes the row).
- Otherwise the default.

**One way to read.** `housecairn.instance.config.get_setting(key)` is the only access in
the code. The Django names (`HOUSECAIRN_SIGNUP_OPEN`, `EMAIL_HOST` ...) still exist in
`settings.py` and hold the value read from the variables or the default: they are the
two lower layers, not an access to use.

**Hot reload for every setting of this part.** The database is read through a snapshot that a
process keeps five seconds and drops after each write, so a change reaches the other
processes within five seconds and needs no restart. What Django and django-allauth read
from their own settings follows: `EMAIL_BACKEND` is a backend (`instance.mail`) that
asks `get_setting` for each message, and the verification of addresses and the security alerts
(`ACCOUNT_EMAIL_VERIFICATION`, `ACCOUNT_EMAIL_NOTIFICATIONS`) are updated from the snapshot
when the database sets open sign-up or the mail server, and restored when it no longer does.
`ACCOUNT_EMAIL_VERIFICATION` set by variable stays as the operator chose. Each setting
declares `reload` (`live` or `restart`); none of this part needs a restart.

**Secrets** (the SMTP password) are write-only: the interface and the API say only whether
one is in force. In the database they are encrypted with Fernet (the `cryptography`
package) under a key derived with HKDF from `SECRET_KEY`, versioned (`v1:`). If the key
changes, decryption fails: the secret counts as not set, the screen says the stored one can
no longer be read, a warning is logged without the value, and the administrator enters it
again. `SECRET_KEY_FALLBACKS` is tried too, so a rotation can keep secrets. A secret set by
variable is shown as "set". Secrets never go to the audit log, the API, the exports or the logs.

**Changing a setting** needs an instance administrator, signed in within
`ACCOUNT_REAUTHENTICATION_TIMEOUT` (five minutes), through the web or the API (never an API
token). A value is checked for its kind and range, and together (open sign-up is refused
without a mail server). Restoring a default is checked the same way, on the state it would
leave: the mail server cannot be removed while sign-up is open, in the database or by
variable. It is written in the audit log with the setting and the old and new values, except
a secret. Re-authentication does not replay a form: a secret typed in it must not be stored in
the session. An account with no password, passkey or authenticator (single sign-on only) has
nothing to re-authenticate with: as django-allauth does, its session counts as recent, so for
such an administrator the five-minute rule does not apply and only the identity provider's
session policy protects the settings.

**The mail test** opens a connection to the server and port in force and closes it; it is
never required. Since an administrator chooses that host and port, and the answer tells a
refused login, a TLS failure and no answer apart, it lets an administrator probe a host and
port from the instance's network. That is accepted: it is kept to instance administrators
(no member, no API token) and limited to five tests a minute per administrator.

**Left in the environment**: everything needed before a database exists or able to lock
the administrator out: `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`,
`HOUSECAIRN_DATA_DIR`, the proxy settings, `DEBUG`, the worker counts and the first
administrator. The screen lists them read-only, without secrets.

**Documented and checked**: `docs/administration/settings.md` holds the table of settings
(setting, variable, section, default, effect), generated by `manage.py settings_table`;
a test fails when it differs from the registry.

## Consequences

- A setting added to the registry without its documentation row fails the tests.
- Each request refreshes the snapshot when it is old: a query every five seconds per process.
- A database that cannot be read keeps the last values read in that process; before any
  (before `migrate`), it falls back to variables and defaults.
- Checks of `manage.py check` read the variables and defaults, except `housecairn.E001` (open
  sign-up by variable without a mail server), which also counts a mail server stored in the
  database; the rules between settings keep that server while sign-up is open.
- The "last way to sign in" guard has nothing to protect yet: it comes with the
  single sign-on providers.
