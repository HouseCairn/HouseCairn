# Architecture decision records

Each significant architecture decision is recorded here, in a short format:
context, decision, consequences. A record is never rewritten once accepted: a
later record supersedes it.

| No. | Decision | Date |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions-and-dependencies.md) | Record decisions; runtime dependencies | 2026-11-07 |
| [0002](0002-single-service-layer.md) | A single service layer for web and API | 2026-11-07 |
| [0003](0003-web-api-parity.md) | Web/API parity, checked by a test | 2026-11-07 |
| [0004](0004-versioned-rest-api.md) | Versioned REST API, OpenAPI 3.1, cursor pagination | 2026-11-07 |
| [0005](0005-stable-identifiers-and-soft-deletion.md) | UUID identifiers, timestamps, soft deletion | 2026-11-07 |
| [0006](0006-home-scoping.md) | Every query scoped to the user's homes | 2026-11-07 |
| [0007](0007-authentication-and-api-tokens.md) | django-allauth, scoped API tokens, OAuth 2 later | 2026-11-07 |
| [0008](0008-background-tasks.md) | Background tasks with django-q2 and the ORM broker | 2026-11-07 |
| [0009](0009-design-tokens.md) | Design tokens in one JSON file | 2026-11-07 |
| [0010](0010-stable-urls.md) | Stable addresses for every record | 2026-11-07 |
| [0011](0011-no-external-resources-and-csp.md) | No external resources, strict CSP | 2026-11-07 |
| [0012](0012-configuration-and-security-defaults.md) | Configuration by environment, safe defaults | 2026-11-07 |
| [0013](0013-internationalization.md) | English source, French shipped, no hard-coded strings | 2026-11-07 |
| [0014](0014-continuous-integration-and-supply-chain.md) | Continuous integration and supply-chain security | 2026-11-07 |
