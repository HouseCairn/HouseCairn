# Environment variables

Set them in `deploy/production.env`. The full list, with defaults, is in
[`deploy/production.env.example`](../../deploy/production.env.example) and
[`.env.example`](../../.env.example).

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALLOWED_HOSTS` | (none: required) | Host names HouseCairn answers to, comma-separated. |
| `CSRF_TRUSTED_ORIGINS` | (none) | `https://` origins of those host names. |
| `HOUSECAIRN_BEHIND_TLS_PROXY` | `false` | `true` behind a reverse proxy that sets `X-Forwarded-Proto`. |
| `HOUSECAIRN_FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Addresses or networks of that proxy, comma-separated: only their forwarding headers count (see [Reverse proxy](reverse-proxy.md)). |
| `SECRET_KEY` | generated in `/data/secret_key` | Set it only to manage the key yourself. |
| `DATABASE_URL` | SQLite in `/data` | For example `postgres://housecairn:<password>@postgres:5432/housecairn`. |
| `TIME_ZONE` | `UTC` | Time zone of the instance. |
| `HOUSECAIRN_SIGNUP_OPEN` | `false` | Allow local sign-up from the web page. |
| `OIDC_SERVER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | (none) | Single sign-on through any OpenID Connect provider. |
| `HOUSECAIRN_OIDC_SIGNUP`, `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL` | `closed`, (none) | Who may get an account through single sign-on. |
| `HOUSECAIRN_DOCS_URL` | `https://docs.housecairn.app` | Address of this documentation, used by the help link of each screen. |
| `HOUSECAIRN_WEB_WORKERS` | `2` | Web server processes. |
| `HOUSECAIRN_TASK_WORKERS` | `2` | Task worker processes. |
| `HOUSECAIRN_STOP_TIMEOUT` | `20` | Seconds given to both to stop; keep it below Compose's `stop_grace_period`. |
| `HOUSECAIRN_PORT` | `8000` | Port inside the container. |
| `LOG_LEVEL` | `INFO` | Application log level; logs go to the container output. |

Set inside the image, not to be changed: `HOUSECAIRN_DATA_DIR=/data`,
`STATIC_ROOT=/app/static`, `DJANGO_SETTINGS_MODULE=housecairn.settings`.

## PostgreSQL

SQLite is the default and is enough for a household. To use PostgreSQL, the
example `compose.yaml` has a `postgres` service, started only with the
`postgres` profile:

1. `cp deploy/postgres.env.example deploy/postgres.env` and set a password.
2. In `deploy/production.env`, set
   `DATABASE_URL=postgres://housecairn:<password>@postgres:5432/housecairn`.
3. Uncomment `depends_on` in the `housecairn` service, then
   `docker compose --profile postgres up -d`.

An existing PostgreSQL server works too: set `DATABASE_URL` to it.
