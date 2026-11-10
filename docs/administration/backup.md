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

The simplest complete backup, while HouseCairn runs, is one command
([ADR 0048](../adr/0048-export-format-and-restore.md)):

```sh
docker compose exec housecairn python -m housecairn.entrypoint manage backup_instance
# prints /data/backups/housecairn-<UTC date and time>.tar
```

The archive holds a consistent copy of the database (SQLite's online backup
API, the same as `sqlite3 db.sqlite3 ".backup ..."`; with PostgreSQL,
`pg_dump --format=custom`, which must be installed where the command runs), the
uploaded files of `/data/media/`, the secret key, and `manifest.json` with the
SHA-256 digest of each. It is written with mode 600: it holds every home and
the secret key, keep it as safe as the server. Copy it off the machine, and
remove old copies from `/data/backups/` yourself. `--output <directory>`
writes it elsewhere.

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

Stop the application (and keep the database service running if it is
PostgreSQL), then restore the archive of `backup_instance`, and start the
application again:

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
