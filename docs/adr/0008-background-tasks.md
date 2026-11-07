# 0008. Background tasks with django-q2 and the ORM broker

- Status: accepted
- Date: 2026-11-07

## Context

Reminders, notifications, polling of optional integrations and exports run
outside the request. Housecairn ships as a single container with SQLite by
default: no Redis, no separate message broker.

## Decision

django-q2 with the ORM broker on the default database (SQLite or PostgreSQL).
The worker (`manage.py qcluster`) runs in the same container as the web
process. Tasks are plain functions in `<app>/tasks.py` and are queued by
services, never by views. `HOUSECAIRN_TASKS_SYNC=true` runs tasks inline (tests).
The demonstration task `core.tasks.heartbeat`, queued by
`core.services.enqueue_heartbeat`, is tested end to end.

SQLite runs in WAL mode with `IMMEDIATE` transactions so the web process and
the worker can write concurrently.

## Consequences

- No extra service to run; throughput is ample for a household.
- Task results are kept in the database (`save_limit` 250).
- A larger deployment can switch to PostgreSQL without code changes.
