# API

HouseCairn has a REST API, mounted at `/api/v1/`, with the same rules as the
web interface: every request only sees the homes of its user
([ADR 0004](../adr/0004-versioned-rest-api.md),
[ADR 0006](../adr/0006-home-scoping.md)).

- **JSON** for requests and responses, except the upload of a photo, which is
  `multipart/form-data` (`POST /api/v1/homes/<home id>/photos/`), and the image
  and thumbnail of a photo, which are served as images.
- **Versioned**: version 1 only gets additive changes; a breaking change will
  go to `/api/v2/`, served alongside version 1 for a deprecation period.
- **Cursor pagination**, up to 200 items per page.
- **Updates** with `PATCH`; `PUT` is not offered.
- **Authentication** by API token, `Authorization: Bearer hc_...`, with the
  scopes `read`, `write` and `events`, bound to one or more homes and expiring
  after 90 days by default
  ([ADR 0007](../adr/0007-authentication-and-api-tokens.md)). There is no
  screen to create a token yet.
- **Rooms, items and photos** of a home: `/api/v1/homes/<home id>/rooms/`,
  `.../items/`, `.../photos/` and `.../search/?q=`, with the same rules as the
  screens ([ADR 0029](../adr/0029-rooms-items-and-room-memory.md),
  [ADR 0030](../adr/0030-photo-storage-and-processing.md)). A token needs the
  `read` scope to read them and `write` to change them, and its user needs a role
  that writes. Rooms and items can be filtered with `q` (name); items with
  `room`; photos with `room`, `item` and `category`.

The [reference](reference.md) lists every operation. It is generated from the
OpenAPI 3.1 schema of the code at each build of this site:
{download}`download the schema (openapi.json) </_generated/openapi.json>`.
A running instance serves the same schema at `/api/schema/` and an
interactive explorer at `/api/docs/`, both to signed-in users only.

```{toctree}
:maxdepth: 1

reference
```
