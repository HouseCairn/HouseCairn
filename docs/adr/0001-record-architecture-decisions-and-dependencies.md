# 0001. Record architecture decisions; runtime dependencies

- Status: accepted
- Date: 2026-11-07

## Context

Housecairn is built in small pull requests, by contributors and by an AI agent
under human review. Decisions taken in one pull request must be visible to the
next one, and the reasons behind them must survive. Every runtime dependency is
also code we ship and must keep up to date.

## Decision

Architecture decisions are recorded in `docs/adr/`, one file per decision, in
the format context, decision, consequences.

Runtime dependencies are limited to well-maintained projects that replace code
we would otherwise write (principle "do not reinvent"):

| Package | Why |
| --- | --- |
| Django 5.2 LTS | Web framework, long-term support release. |
| djangorestframework | REST API (0004). |
| drf-spectacular, drf-spectacular-sidecar | OpenAPI 3.1 schema and a locally served interface (0004, 0011). |
| django-allauth, with its `mfa` and `socialaccount` extras | Local accounts, TOTP, passkeys, generic OpenID Connect (0007). The extras pull in `fido2` (passkeys) and the OAuth/OIDC client libraries (`requests`, `PyJWT`, `cryptography`); they are part of allauth's own feature set, not separate choices. |
| django-q2 | Background tasks (0008). |
| django-environ | Configuration from environment variables (0012). |
| django-csp | Content Security Policy (0011). |
| python-dateutil | RFC 5545 recurrence rules, needed from the tasks lot onwards. |
| Pillow | Decodes and writes again the photos of rooms and items, to check their content and drop their metadata (0030). |
| django-stubs-ext | Lets generic classes such as `ModelAdmin[Home]` be subscripted at runtime for the type checker. Companion of django-stubs, maintained by the same project, no runtime behaviour otherwise. |

Optional runtime dependency, installed with the `postgres` extra
(`uv sync --extra postgres`) only by instances that use PostgreSQL:

| Package | Why |
| --- | --- |
| psycopg, with its `binary` extra | PostgreSQL driver supported by Django. The `binary` extra ships a prebuilt `libpq`, so no compiler or system library is needed. Added by ADR 0014, which tests every pull request on PostgreSQL. |

Development tools: uv (locking), ruff, mypy with django-stubs and
djangorestframework-stubs, pytest, pytest-django, pytest-cov.

## Consequences

- Adding a runtime dependency requires a new ADR, or an amendment to this one in
  the same pull request.
- `uv.lock` pins every package; updates go through pull requests.
