# Data and backups

Everything HouseCairn writes is in the `/data` volume:

| Path | Content |
| --- | --- |
| `/data/db.sqlite3` (and `-wal`, `-shm`) | The SQLite database, unless `DATABASE_URL` points to PostgreSQL. |
| `/data/secret_key` | The key that signs sessions and tokens, mode 600. Losing it signs everyone out; keep it secret. |
| `/data/media/` | Uploaded files. |
| `/data/backups/` | Copies made by the `backup_instance` and `backup` commands below. |

Files are owned by `10001:10001` and readable by that user only. If you mount a
host directory instead of a named volume, give it to that user first:
`sudo chown -R 10001:10001 /srv/housecairn`.

## Back up

With SQLite, the default, the simplest complete backup, while HouseCairn runs,
is one command ([ADR 0048](../adr/0048-export-format-and-restore.md)):

```sh
docker compose exec housecairn python -m housecairn.entrypoint manage backup_instance
# prints /data/backups/housecairn-<UTC date and time>.tar
```

The archive holds a consistent copy of the database (SQLite's online backup
API, the same as `sqlite3 db.sqlite3 ".backup ..."`), the uploaded files of
`/data/media/`, the secret key, and `manifest.json` with the SHA-256 digest of
each. It is written with mode 600: it holds every home and
the secret key, keep it as safe as the server. Copy it off the machine, and
remove old copies from `/data/backups/` yourself. `--output <directory>`
writes it elsewhere.

### With PostgreSQL

With PostgreSQL, `backup_instance` calls `pg_dump`, and `restore_instance`
calls `pg_restore`. **The official image contains neither**: in it, both
commands stop with `pg_dump is not installed in this container` (or
`pg_restore`). Back up the two parts separately instead, with the `postgres`
service of `compose.yaml`, whose image has both programs and is of the same
version as the server:

```sh
# 1. The database, in pg_dump's custom format, written on the host.
docker compose --profile postgres exec -T postgres \
  pg_dump -U housecairn -d housecairn --format=custom > housecairn-db.dump

# 2. The uploaded files and the secret key, from the volume, read only.
docker run --rm -v housecairn_housecairn-data:/data:ro -v "$PWD":/backup \
  debian:stable-slim tar -cf /backup/housecairn-files.tar -C /data media secret_key
```

If `SECRET_KEY` is set in `deploy/production.env` rather than generated in
`/data/secret_key`, leave `secret_key` out of the second command and keep a copy
of `production.env` instead. Both files hold every home; keep them as safe as
the server.

These commands follow the `compose.yaml` of the repository (service, user,
database and volume names), but have not yet been tried on a real server: try
a restore on another machine before you rely on them.

Two other ways remain:

- **Cold copy**: stop the container, copy the volume, start it again.

  ```sh
  docker compose stop housecairn
  docker run --rm -v housecairn_housecairn-data:/data:ro -v "$PWD":/backup \
    debian:stable-slim tar -czf /backup/housecairn-data.tar.gz -C /data .
  docker compose start housecairn
  ```

  (The volume name is `<project>_housecairn-data`; `docker volume ls` shows it.)

- **The database only**, with `python -m housecairn.entrypoint backup`
  (prints `/data/backups/db-<UTC date and time>.sqlite3`); then copy
  `/data/secret_key` and `/data/media/` as well.

The owners of a home can also keep their own copy of it: **Export all data**,
which a restore makes a new home again ([Export and deletion](data.md)).

## Restore

With SQLite, stop the application, then restore the archive of
`backup_instance`, and start the application again:

```sh
docker compose run --rm housecairn python -m housecairn.entrypoint manage \
  restore_instance /data/backups/housecairn-20261110T120000Z.tar --yes
```

Every part is checked against the manifest first; a changed backup, a name that
leaves its directory or a link is refused and nothing is replaced. The
database, `/data/media/` and the secret key that were there are not deleted:
they are kept next to it, renamed `<name>.before-restore-<date>`, until you
remove them. Without `--yes`, the command refuses to replace anything.

To check a backup without touching the instance, restore it elsewhere:

```sh
python -m housecairn.entrypoint manage restore_instance <backup>.tar \
  --database-file /tmp/check/db.sqlite3 --media-root /tmp/check/media \
  --data-dir /tmp/check
```

For a cold copy, stop the container, put the files back in the volume (owned
by `10001:10001`), and start it.

With PostgreSQL, restore the two parts of [With PostgreSQL](#with-postgresql),
the application stopped and the `postgres` service running:

```sh
docker compose stop housecairn
docker compose --profile postgres exec -T postgres \
  pg_restore -U housecairn -d housecairn --clean --if-exists --no-owner \
  --single-transaction < housecairn-db.dump
docker run --rm -v housecairn_housecairn-data:/data -v "$PWD":/backup \
  debian:stable-slim sh -c \
  'tar -xf /backup/housecairn-files.tar -C /data && chown -R 10001:10001 /data'
docker compose start housecairn
```

`--clean --if-exists` drops each table of the dump before it is recreated, so
the database is the one of the dump; `--single-transaction` leaves it as it
was if anything fails. Unlike `restore_instance`, the files are not checked
against a manifest and those already in `/data/media/` are overwritten, not
kept aside. Like the backup, this has not yet been tried on a real server.
