# Architecture

Housecairn is a Django application with HTMX for the interactive parts, in a
single container. The main rules, each recorded in a decision:

- **One service layer** holds the business rules; web views and API views
  call it and hold none of their own
  ([ADR 0002](../adr/0002-single-service-layer.md)).
- **Web and API parity**: what the web interface does, the API does too,
  checked by a test ([ADR 0003](../adr/0003-web-api-parity.md)).
- **Every query is scoped** to the homes of the user, or of the API token
  ([ADR 0006](../adr/0006-home-scoping.md)).
- **Stable identifiers and addresses**: UUIDs, soft deletion, addresses that
  do not change ([ADR 0005](../adr/0005-stable-identifiers-and-soft-deletion.md),
  [ADR 0010](../adr/0010-stable-urls.md)).
- **Background tasks** with django-q2 and the database as broker
  ([ADR 0008](../adr/0008-background-tasks.md)).
- **No external resource** and a strict Content Security Policy
  ([ADR 0011](../adr/0011-no-external-resources-and-csp.md)).
- **English source, French shipped**, no hard-coded string
  ([ADR 0013](../adr/0013-internationalization.md)).

The code is in `src/housecairn/`, one Django application per domain
(`accounts`, `apitokens`, `core`, `events`, `homes`).
