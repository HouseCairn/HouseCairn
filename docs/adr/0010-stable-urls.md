# 0010. Stable addresses for every record

- Status: accepted
- Date: 2026-11-07

## Context

QR labels stuck on appliances, universal links opening the iOS app, and links
shared between members must keep working for years.

## Decision

Web addresses follow one convention:

| Address | Content |
| --- | --- |
| `/` | Landing page |
| `/h/` | The user's homes |
| `/h/<home_id>/` | One home |
| `/h/<home_id>/<collection>/` | A collection in a home, for example `rooms`, `items`, `tasks` |
| `/h/<home_id>/<collection>/<uuid>/` | One record, for example `/h/<home_id>/items/<uuid>/` |
| `/accounts/...` | Sign-in and account (allauth) |
| `/api/v1/...` | API (0004) |
| `/healthz` | Health probe |

- Identifiers are the records' UUIDs (0005), never names or slugs, so renaming
  never breaks a link.
- Collection names are English plural nouns, lowercase, stable once released.
- API paths mirror the web paths under `/api/v1/homes/<home_id>/...`.
- A link to a record the user cannot see answers 404 (0006); a QR label always
  asks for sign-in first.

## Consequences

- An address, once released, is kept; if a screen moves, the old address
  redirects permanently.
- The first routes (`/h/`, `/h/<home_id>/`) already follow the convention.
