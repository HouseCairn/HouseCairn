# Data and backups

Everything HouseCairn writes is in the `/data` volume:

| Path | Content |
| --- | --- |
| `/data/db.sqlite3` (and `-wal`, `-shm`) | The SQLite database, unless `DATABASE_URL` points to PostgreSQL. |
| `/data/secret_key` | The key that signs sessions and tokens, mode 600. Losing it signs everyone out; keep it secret. |
| `/data/media/` | Uploaded files. |
| `/data/backups/` | Copies made by the `backup` command below. |

Files are owned by `10001:10001` and readable by that user only. If you mount a
host directory instead of a named volume, give it to that user first:
`sudo chown -R 10001:10001 /srv/housecairn`.

## Back up

Back up `/data` in one of two ways:

- **Cold copy**, the simplest: stop the container, copy the volume, start it
  again.

  ```sh
  docker compose stop housecairn
  docker run --rm -v housecairn_housecairn-data:/data:ro -v "$PWD":/backup \
    debian:stable-slim tar -czf /backup/housecairn-data.tar.gz -C /data .
  docker compose start housecairn
  ```

  (The volume name is `<project>_housecairn-data`; `docker volume ls` shows it.)

- **Online copy of the database**, while HouseCairn runs, with SQLite's backup
  API (the same as `sqlite3 db.sqlite3 ".backup ..."`):

  ```sh
  docker compose exec housecairn python -m housecairn.entrypoint backup
  # prints /data/backups/db-<UTC date and time>.sqlite3
  ```

  Then copy `/data/backups/`, `/data/secret_key` and `/data/media/` off the
  machine. Remove old copies from `/data/backups/` yourself.

With PostgreSQL, back up the database with `pg_dump`, and `/data` for the key
and the uploaded files.

## Restore

To restore, stop the container, put the files back in the volume (owned by
`10001:10001`), and start it.
