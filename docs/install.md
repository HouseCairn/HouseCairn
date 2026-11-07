# Installing Housecairn with Docker Compose

> Housecairn is in early development and not usable yet. This page describes
> how the container image works, so that it can be tested.

Housecairn ships as a single container image, `ghcr.io/housecairn/housecairn`,
for `linux/amd64` and `linux/arm64`. It holds the web server, the background
task worker and the static files. Everything it writes goes to one volume,
`/data`. The design decisions behind the image are in
[ADR 0015](adr/0015-container-image-and-publication.md).

## Requirements

- Docker Engine with the Compose plugin (`docker compose`).
- A reverse proxy that terminates HTTPS in front of Housecairn (Caddy, Traefik,
  nginx...). Housecairn listens on plain HTTP, port 8000, and redirects every
  request to HTTPS; it expects the proxy to set `X-Forwarded-Proto`.

## Install

1. Get `compose.yaml` and `deploy/production.env.example` from the repository,
   in the same layout:

   ```sh
   mkdir -p housecairn/deploy && cd housecairn
   curl -fsSLO https://raw.githubusercontent.com/HouseCairn/HouseCairn/main/compose.yaml
   curl -fsSL -o deploy/production.env \
     https://raw.githubusercontent.com/HouseCairn/HouseCairn/main/deploy/production.env.example
   ```

2. Edit `deploy/production.env`: set `ALLOWED_HOSTS` and
   `CSRF_TRUSTED_ORIGINS` to your host name (see
   [Environment variables](#environment-variables)). Leave `SECRET_KEY` empty:
   a key is generated on first start.
3. In `compose.yaml`, replace the `edge` tag with a released version, ideally
   with its digest (`ghcr.io/housecairn/housecairn:X.Y.Z@sha256:...`).
   [Verify the image](#verify-the-image) before the first start.
4. Start it, then check its state:

   ```sh
   docker compose up -d
   docker compose ps          # STATUS shows "healthy" after a few seconds
   docker compose logs -f housecairn
   ```

5. Point your reverse proxy at `http://127.0.0.1:8000`.

On every start, the container creates the secret key if it is missing,
applies the database migrations, then starts the web server (gunicorn, two
processes by default) and the task worker (django-q2). If either stops, the
container stops, and Compose restarts it.

### The first administrator

The image creates no account and has no default password. The first
administrator comes from one of these, right after the first start:

- **Single sign-on (OpenID Connect).** Set `OIDC_SERVER_URL`,
  `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`, and preferably
  `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL`. The first person to sign in through the
  provider becomes the instance administrator; if the address is set, only an
  identity with that verified address can. See
  [ADR 0007](adr/0007-authentication-and-api-tokens.md).
- **A local account**, created from the command line:

  ```sh
  docker compose exec housecairn python -m housecairn.entrypoint manage createsuperuser
  ```

  Local sign-up from the web page stays closed unless
  `HOUSECAIRN_SIGNUP_OPEN=true`.

## Hardening

`compose.yaml` runs the container the recommended way:

| Setting | Effect |
| --- | --- |
| `read_only: true` | The image's file system cannot be modified. Only `/data` and `/tmp` are writable. |
| `tmpfs: /tmp` | Temporary files (large uploads in progress) stay in memory, 64 MB at most, and disappear at restart. |
| `cap_drop: [ALL]` | No Linux capability: the application needs none. |
| `security_opt: no-new-privileges:true` | No process can gain privileges, even through a set-user-ID binary. |
| user `10001:10001` | Set in the image; the application never runs as root. |

The same settings with `docker run`:

```sh
docker run -d --name housecairn \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges \
  --env-file deploy/production.env \
  -v housecairn-data:/data -p 127.0.0.1:8000:8000 \
  ghcr.io/housecairn/housecairn:X.Y.Z
```

`/healthz` answers `{"status": "ok"}` without authentication and reveals
nothing else; the image's `HEALTHCHECK` calls it.

## Data and backups

Everything Housecairn writes is in the `/data` volume:

| Path | Content |
| --- | --- |
| `/data/db.sqlite3` (and `-wal`, `-shm`) | The SQLite database, unless `DATABASE_URL` points to PostgreSQL. |
| `/data/secret_key` | The key that signs sessions and tokens, mode 600. Losing it signs everyone out; keep it secret. |
| `/data/media/` | Uploaded files. |
| `/data/backups/` | Copies made by the `backup` command below. |

Files are owned by `10001:10001` and readable by that user only. If you mount a
host directory instead of a named volume, give it to that user first:
`sudo chown -R 10001:10001 /srv/housecairn`.

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

- **Online copy of the database**, while Housecairn runs, with SQLite's backup
  API (the same as `sqlite3 db.sqlite3 ".backup ..."`):

  ```sh
  docker compose exec housecairn python -m housecairn.entrypoint backup
  # prints /data/backups/db-<UTC date and time>.sqlite3
  ```

  Then copy `/data/backups/`, `/data/secret_key` and `/data/media/` off the
  machine. Remove old copies from `/data/backups/` yourself.

With PostgreSQL, back up the database with `pg_dump`, and `/data` for the key
and the uploaded files.

To restore, stop the container, put the files back in the volume (owned by
`10001:10001`), and start it.

## Update

1. Read the release notes of the new version.
2. Back up `/data` (above).
3. Change the tag (and digest) in `compose.yaml`, verify the new image, then:

   ```sh
   docker compose pull
   docker compose up -d
   ```

Migrations run at start. Going back to an older version after its migrations
have run needs the backup.

## Environment variables

Set them in `deploy/production.env`. The full list, with defaults, is in
[`deploy/production.env.example`](../deploy/production.env.example) and
[`.env.example`](../.env.example).

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALLOWED_HOSTS` | (none: required) | Host names Housecairn answers to, comma-separated. |
| `CSRF_TRUSTED_ORIGINS` | (none) | `https://` origins of those host names. |
| `HOUSECAIRN_BEHIND_TLS_PROXY` | `false` | `true` behind a reverse proxy that sets `X-Forwarded-Proto`. |
| `SECRET_KEY` | generated in `/data/secret_key` | Set it only to manage the key yourself. |
| `DATABASE_URL` | SQLite in `/data` | For example `postgres://housecairn:<password>@postgres:5432/housecairn`. |
| `TIME_ZONE` | `UTC` | Time zone of the instance. |
| `HOUSECAIRN_SIGNUP_OPEN` | `false` | Allow local sign-up from the web page. |
| `OIDC_SERVER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | (none) | Single sign-on through any OpenID Connect provider. |
| `HOUSECAIRN_OIDC_SIGNUP`, `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL` | `closed`, (none) | Who may get an account through single sign-on. |
| `HOUSECAIRN_WEB_WORKERS` | `2` | Web server processes. |
| `HOUSECAIRN_TASK_WORKERS` | `2` | Task worker processes. |
| `HOUSECAIRN_STOP_TIMEOUT` | `20` | Seconds given to both to stop; keep it below Compose's `stop_grace_period`. |
| `HOUSECAIRN_PORT` | `8000` | Port inside the container. |
| `LOG_LEVEL` | `INFO` | Application log level; logs go to the container output. |

Set inside the image, not to be changed: `HOUSECAIRN_DATA_DIR=/data`,
`STATIC_ROOT=/app/static`, `DJANGO_SETTINGS_MODULE=housecairn.settings`.

### PostgreSQL

SQLite is the default and is enough for a household. To use PostgreSQL, the
example `compose.yaml` has a `postgres` service, started only with the
`postgres` profile:

1. `cp deploy/postgres.env.example deploy/postgres.env` and set a password.
2. In `deploy/production.env`, set
   `DATABASE_URL=postgres://housecairn:<password>@postgres:5432/housecairn`.
3. Uncomment `depends_on` in the `housecairn` service, then
   `docker compose --profile postgres up -d`.

An existing PostgreSQL server works too: set `DATABASE_URL` to it.

## Verify the image

Every image published by the project's workflow has two signed attestations,
made with GitHub's artifact attestations (Sigstore):

- **build provenance** (SLSA), on the multi-platform image: which workflow,
  commit and repository built it;
- **SBOM** (SPDX), on each platform's image: every package it contains.

Verify them with the GitHub CLI before you deploy:

```sh
# Provenance: built by this repository's workflow, from this repository.
gh attestation verify oci://ghcr.io/housecairn/housecairn:X.Y.Z \
  --repo HouseCairn/HouseCairn \
  --signer-workflow HouseCairn/HouseCairn/.github/workflows/image.yml

# SBOM of the linux/amd64 image (use its digest, shown by the first command
# below), and its list of packages.
docker buildx imagetools inspect ghcr.io/housecairn/housecairn:X.Y.Z
gh attestation verify oci://ghcr.io/housecairn/housecairn@sha256:<amd64 digest> \
  --repo HouseCairn/HouseCairn --predicate-type https://spdx.dev/Document/v2.3
```

A successful verification ends with `✓ Verification succeeded!`. The
attestations are also stored in the registry next to the image.

## Tags

| Tag | Points to |
| --- | --- |
| `X.Y.Z` | A release. |
| `X.Y` | The most recently published `X.Y.*` release. |
| `latest` | The most recently published release (never a pre-release). |
| `X.Y.Z-rc.N` | A pre-release. |
| `edge` | The latest commit on `main`: for testing, not for production. |
| `sha-<commit>` | The image built from that commit. |

Pin a version and its digest in production; a tag can move, a digest cannot.
