# API

HouseCairn has a REST API, mounted at `/api/v1/`, with the same rules as the
web interface: every request only sees the homes of its user
([ADR 0004](../adr/0004-versioned-rest-api.md),
[ADR 0006](../adr/0006-home-scoping.md)).

- **JSON** only, for requests and responses.
- **Versioned**: version 1 only gets additive changes; a breaking change will
  go to `/api/v2/`, served alongside version 1 for a deprecation period.
- **Cursor pagination**, up to 200 items per page.
- **Updates** with `PATCH`; `PUT` is not offered.
- **Authentication** by API token, `Authorization: Bearer hc_...`, with the
  scopes `read`, `write` and `events`, bound to one or more homes and expiring
  after 90 days by default
  ([ADR 0007](../adr/0007-authentication-and-api-tokens.md)). There is no
  screen to create a token yet.

The [reference](reference.md) lists every operation. It is generated from the
OpenAPI 3.1 schema of the code at each build of this site:
{download}`download the schema (openapi.json) </_generated/openapi.json>`.
A running instance serves the same schema at `/api/schema/` and an
interactive explorer at `/api/docs/`, both to signed-in users only.

```{toctree}
:maxdepth: 1

reference
```
