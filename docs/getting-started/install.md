# Install with Docker Compose

HouseCairn ships as a single container image, `ghcr.io/housecairn/housecairn`,
for `linux/amd64` and `linux/arm64`. It holds the web server, the background
task worker and the static files. Everything it writes goes to one volume,
`/data`. The design decisions behind the image are in
[ADR 0015](../adr/0015-container-image-and-publication.md).

## Requirements

- Docker Engine with the Compose plugin (`docker compose`).
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
   empty: a key is generated on first start.
3. In `compose.yaml`, replace the `edge` tag with a released version, ideally
   with its digest (`ghcr.io/housecairn/housecairn:X.Y.Z@sha256:...`).
   [Verify the image](../security/verify-image.md) before the first start.
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

Next: [create the first administrator](first-start.md).
