# 0002. A single service layer for web and API

- Status: accepted
- Date: 2026-11-07

## Context

The web interface, a future native iOS app, Home Assistant and an MCP server
will all act on the same data. If business rules live in views, serializers or
templates, each client ends up with its own, slightly different version.

## Decision

Business rules live in `src/housecairn/<app>/services.py`: plain Python
functions taking the acting user and model instances. Web views and API views
validate input, call a service, and render the result. Rules include who may
do what (for example `homes.services.can_write`), invariants and side effects.

- Views, serializers and templates contain no business rule.
- The web interface never calls the API over HTTP; both call the services.
- Services raise `django.core.exceptions.PermissionDenied` or
  `ValidationError`; Django and DRF turn them into 403 and 400 responses.

## Consequences

- A rule is tested once, at the service level, and holds for every client.
- Reviewers reject a pull request that puts a rule in a view or a serializer.
- The admin site also goes through services where it changes state (for
  example token revocation).
