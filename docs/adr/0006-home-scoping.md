# 0006. Every query scoped to the user's homes

- Status: accepted
- Date: 2026-11-07

## Context

One instance serves several homes and several people: a household, a tenant
with read-only access, a craftsperson. A single forgotten filter would expose
another home's data. The filter must be in one place and used everywhere.

## Decision

- `homes.Home` and `homes.Membership` (roles `owner`, `member`, `read_only`)
  exist from the first migration. Every business model inherits
  `homes.models.HomeOwnedModel` (a `home` foreign key and an `in_homes()`
  query method).
- `homes.services.homes_for(user, restrict_to=None)` is the only function that
  decides which homes a user sees: active memberships of an active user,
  optionally narrowed to a token's homes.
- `homes.scoping.HomeScopedMixin` gives web and API views `get_homes()` and
  `get_home()` (from the `home_id` URL parameter). `WebHomeScopedMixin` adds the
  sign-in requirement for web views. A home outside the user's scope answers
  404, never 403, so its existence does not leak.
- Write rights depend on the role (`owner` and `member` write, `read_only`
  reads), decided by `homes.services.can_write`.

## Consequences

- New business views start from these mixins and query
  `Model.objects.in_homes(self.get_homes())`.
- Tests for each new resource must include the "other user's home" case, by
  the web and by the API, as `tests/test_homes.py` does for homes.
