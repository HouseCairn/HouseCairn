# 0004. Versioned REST API, OpenAPI 3.1, cursor pagination

- Status: accepted
- Date: 2026-11-07

## Context

An iOS app installed months ago must keep working against a newer server. API
clients need a machine-readable contract, and lists that grow while being read
(tasks, history) must page reliably.

## Decision

- Django REST Framework, mounted at `/api/v1/` (namespace `api-v1`). A
  breaking change goes to `/api/v2/`, served alongside v1 for a deprecation
  period; v1 only gets additive changes.
- drf-spectacular generates an OpenAPI 3.1 schema at `/api/schema/`; Swagger UI
  is served at `/api/docs/` from drf-spectacular-sidecar, never from a CDN. Both
  require a signed-in user. `manage.py spectacular --validate --fail-on-warn`
  must pass.
- JSON only for requests and responses; no browsable API.
- Cursor pagination by default (`-created_at`, `-id`), `page_size` up to 200:
  stable when rows are inserted, no total count to compute.
- `PATCH` for updates; `PUT` is not offered.
- Authentication: API tokens (0007), then session for the web interface's own
  calls.

## Consequences

- Clients follow `next` links instead of computing offsets.
- The schema is the reference for client generation and for the API pages of
  the documentation site.
