# 0025. Rate-limit counters and several web processes

- Status: accepted
- Date: 2026-11-08

## Context

Rate limits (invitations, sign-up, sign-in, deletion of an account) are
counted by django-allauth's limiter in Django's cache. The default cache is in
the memory of one process. The image runs two web processes by default
(`HOUSECAIRN_WEB_WORKERS`), so each counts alone: a limit of 30 a minute is, in
the worst case, 60. The limits key on `REMOTE_ADDR`, set by
`ForwardedHeadersMiddleware` from a trusted proxy only (ADR 0012); no code
reads `X-Forwarded-For` itself, and tests forge it to prove it.

## Decision

- The cache is configured by `HOUSECAIRN_CACHE_URL`
  ([django-environ cache URLs](https://django-environ.readthedocs.io/)). The
  default stays `locmemcache://housecairn`: one container, no extra service,
  and a limit up to `HOUSECAIRN_WEB_WORKERS` times looser.
- For an exact limit, `HOUSECAIRN_CACHE_URL=dbcache://housecairn_cache` puts the
  counters in the database the web processes already share. The image creates
  the table at start-up (`createcachetable`, a no-op for other caches). A
  Redis or Memcached URL works too. File-based caches are possible but not
  advised on a read-only file system.
- The documentation says which limit is per process and how to make it shared.

## Consequences

- With the default, a patient client spreads its attempts across processes;
  the rate limits remain a brake, with the verification of addresses and the
  proof of work as the other barriers.
- A database cache adds a few queries to the requests that are limited
  (sign-in, sign-up, invitation links) and nothing to the others.
