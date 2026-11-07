# 0012. Configuration by environment, safe defaults

- Status: accepted
- Date: 2026-11-07

## Context

Housecairn is self-hosted by people who will not read Django's deployment
checklist. The settings they get without changing anything must be the safe
ones (principle P7), and the same image must run anywhere.

## Decision

- One settings module, `housecairn.settings`, configured only by environment
  variables through django-environ. A `.env` file at the repository root, if
  present, fills in missing variables for development; it never overrides the
  environment and is never committed (`.env.example` documents the variables).
- `DEBUG` is false by default. `SECRET_KEY` is required unless `DEBUG` is true.
  `ALLOWED_HOSTS` is empty by default in production.
- Database: `DATABASE_URL`, SQLite in `HOUSECAIRN_DATA_DIR` by default,
  PostgreSQL possible.
- With `DEBUG` off: HTTPS redirect (except `/healthz`), secure, `HttpOnly`,
  `SameSite=Lax` cookies, HSTS for one year, `X-Frame-Options: DENY`, no
  sniffing, `same-origin` referrer and opener policies.
  `HOUSECAIRN_BEHIND_TLS_PROXY=true` trusts `X-Forwarded-Proto` from a reverse
  proxy.
- Forwarding headers (`X-Forwarded-For`, `X-Forwarded-Proto`,
  `X-Forwarded-Host`, `Forwarded`, `X-Real-IP`...) count only from the peers
  of `HOUSECAIRN_FORWARDED_ALLOW_IPS`, by default the loopback. The first
  middleware, `housecairn.core.proxy.ForwardedHeadersMiddleware`, removes them
  from a request of any other peer, and for a trusted proxy replaces
  `REMOTE_ADDR` with the right-most address of `X-Forwarded-For` that is not a
  trusted proxy. django-allauth's rate limits and everything else read
  `REMOTE_ADDR` only (`ALLAUTH_TRUSTED_PROXY_COUNT = 0`). gunicorn gets the
  same list (ADR 0015). `USE_X_FORWARDED_HOST` stays off: the `Host` header
  names the site.
- HSTS `includeSubDomains` and `preload` commit the whole domain, which only its
  owner can decide: they stay off by default, configurable, and Django's
  reminders about them (`security.W005`, `security.W021`) are silenced.
- `/healthz` answers `{"status": "ok"}` or 503 without authentication and
  without any other information.
- Passwords: at least 12 characters, plus Django's similarity, common and
  numeric validators.
- `deploy/production.env.example` is an example production environment;
  `manage.py check --deploy --fail-level WARNING` passes with it and a
  generated `SECRET_KEY`, and a test enforces this.

## Consequences

- Running without a `SECRET_KEY` in production fails at start-up instead of
  running insecurely.
- Local development needs `DEBUG=true`, as in `.env.example`.
