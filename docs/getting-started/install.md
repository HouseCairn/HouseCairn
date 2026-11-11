# Install with Docker Compose

HouseCairn ships as a single container image, `ghcr.io/housecairn/housecairn`,
for `linux/amd64` and `linux/arm64`. It holds the web server, the background
task worker and the static files. Everything it writes goes to one volume,
`/data`. The design decisions behind the image are in
[ADR 0015](../adr/0015-container-image-and-publication.md).

On Coolify, use its own Compose file instead: see
[Deploy with Coolify](../administration/coolify.md).

## Requirements

- Docker Engine 25.0 or later, with the Compose plugin (`docker compose`)
  2.24.0 or later.
  - Engine 25.0: the image's health check checks every 2 seconds while the
    container starts (`--start-interval`), an option that
    [requires Docker Engine 25.0 or later](https://docs.docker.com/reference/dockerfile/#healthcheck)
    ([release notes](https://docs.docker.com/engine/release-notes/25.0/)).
  - Compose 2.24.0: the example `compose.yaml` marks `deploy/postgres.env` as
    optional (`required: false`), which
    [Compose supports since 2.24.0](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/#use-the-env_file-attribute).
  - Check with `docker version --format '{{.Server.Version}}'` and
    `docker compose version`.
- A reverse proxy that terminates HTTPS in front of HouseCairn (Caddy, Traefik,
  nginx...). HouseCairn listens on plain HTTP, port 8000, and redirects every
  request to HTTPS; it expects the proxy to set `X-Forwarded-Proto`. See
  [Reverse proxy](../administration/reverse-proxy.md).

## Install

1. Get `compose.yaml` and `deploy/production.env.example` from the repository,
   in the same layout:

   ```sh
   mkdir -p housecairn/deploy && cd housecairn
   curl -fsSLO https://raw.githubusercontent.com/HouseCairn/housecairn/main/compose.yaml
   curl -fsSL -o deploy/production.env \
     https://raw.githubusercontent.com/HouseCairn/housecairn/main/deploy/production.env.example
   ```

2. Edit `deploy/production.env`: set `ALLOWED_HOSTS` and
   `CSRF_TRUSTED_ORIGINS` to your host name (see
   [Environment variables](../administration/variables.md)). Leave `SECRET_KEY`
   empty: a key is generated on first start. `HOUSECAIRN_FORWARDED_ALLOW_IPS`
   names the reverse proxy whose headers HouseCairn trusts: keep `192.0.2.1`
   for a proxy on this host, the gateway of the network fixed in
   `compose.yaml`.
3. `compose.yaml` names a released version pinned by its digest
   (`ghcr.io/housecairn/housecairn:X.Y.Z@sha256:...`); to install a later one,
   change both. [Verify the image](../security/verify-image.md) before the
   first start.
4. Start it, then check its state:

   ```sh
   docker compose up -d
   docker compose ps          # STATUS shows "healthy" after a few seconds
   docker compose logs -f housecairn
   ```

5. Point your reverse proxy at `http://127.0.0.1:8000`. To run the proxy
   itself in Compose (Caddy or Traefik), see the example in
   [Reverse proxy](../administration/reverse-proxy.md#caddy-or-traefik-in-docker-compose),
   which also gives the value of `HOUSECAIRN_FORWARDED_ALLOW_IPS` for each case.

On every start, the container creates the secret key if it is missing,
applies the database migrations, then starts the web server (gunicorn, two
processes by default) and the task worker (django-q2). If either stops, the
container stops, and Compose restarts it.

HouseCairn also writes a one-time code in this log while it has no administrator:
next, [create the first administrator](first-start.md).
