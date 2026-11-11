# 0060. The secret key: rotation by `SECRET_KEY_FALLBACKS`, kept out of the backups

- Status: accepted
- Date: 2026-11-11
- Amends: [0035](0035-instance-settings-in-the-interface.md) (secrets),
  [0048](0048-export-format-and-restore.md) (backup of the instance)

## Context

The secrets stored in the database (the SMTP password, the secrets of the sign-in providers
added in the interface, the addresses of the notification channels) are encrypted with a key
derived from `SECRET_KEY` (`instance.crypto`). An external audit (2026-11-11) found two gaps.
`instance.crypto` tries `SECRET_KEY_FALLBACKS`, and the documentation advised it for a
rotation, but `settings.py` never read that variable: a rotation lost every stored secret.
And `backup_instance` put `<data>/secret_key` in the archive with the database, so a copy
of the archive gave every stored secret in clear. The maintainer decided on 2026-11-11 that
the key is left out of the backup by default.

## Decision

- **`SECRET_KEY_FALLBACKS` is read from the environment**, a list separated by commas like
  the other lists of `settings.py`, empty entries dropped. Django uses it for sessions and
  signatures, `instance.crypto` for the stored secrets: they are read with any key of the
  list and encrypted again with `SECRET_KEY` when saved again. The procedure is in
  [Settings](../administration/settings.md#rotate-the-key). No command encrypts the stored
  secrets again in bulk: the old key stays in the list for as long as they must be read.
- **The backup leaves the key out.** `backup_instance` writes the database and the files;
  `--include-secret-key` adds `<data>/secret_key`, as before, for whoever asks for it. The
  command says on its error output that the key is not in the archive and where it is.
  The format of the archive does not change (version 1): the key was already an optional
  part, absent when `SECRET_KEY` came from the environment.
- **The restore says what to do without the key.** An archive without the key leaves the
  key of the data directory alone and says: start the instance with the key it had (in
  `SECRET_KEY`, or its file put back), or the stored secrets cannot be read and are entered
  again. Nothing else changes: the database and the files are restored the same way.
- **The documentation says to keep the key apart**: set `SECRET_KEY` in the environment
  rather than leave it generated in `/data`, and keep a copy of it away from the backups
  ([install](../getting-started/install.md), [backup](../administration/backup.md),
  [settings](../administration/settings.md#secrets)).

## Consequences

- An administrator who restores a backup on a new machine needs the key from elsewhere;
  without it the homes are all back, the stored secrets are entered again and everyone
  signs in again.
- A script that relied on the key being in the archive adds `--include-secret-key`; an
  upgrade note says so.
