# Rate limits

Attempts that can be guessed or abused are limited per client address (or per
person when signed in): signing in, signing up, opening invitation links,
sending invitations, erasing an account
([ADR 0025](../adr/0025-rate-limit-counters-and-workers.md)).

| Action | Limit (default) | Variable |
| --- | --- | --- |
| Signing in | 30 a minute per client address | `HOUSECAIRN_RATELIMIT_LOGIN` |
| Failed sign-ins | 5 in five minutes per account, and 10 a minute per client address | `HOUSECAIRN_RATELIMIT_LOGIN_FAILURES` |
| Signing up | 10 a minute and 60 a day per client address | `HOUSECAIRN_RATELIMIT_SIGNUP`, `HOUSECAIRN_RATELIMIT_SIGNUP_DAY` |
| Asking for a password reset | 20 a minute per client address, and 5 a minute per address | `HOUSECAIRN_RATELIMIT_PASSWORD_RESET` |
| Sending or sending again an invitation, to a home or to the instance | 10 a minute and 50 a day per person | `HOUSECAIRN_RATELIMIT_INVITATIONS`, `HOUSECAIRN_RATELIMIT_INVITATIONS_DAY` |
| Opening or accepting an invitation link | 30 a minute per client address | `HOUSECAIRN_RATELIMIT_INVITATION_LINKS` |
| Testing the mail server or an issuer | 5 a minute per administrator | `HOUSECAIRN_RATELIMIT_TESTS` |
| Erasing an account | 5 a minute per person | (fixed) |

Each limit is a setting of the instance: change it on **Instance administration, Settings**,
in the **Rate limits** section, or by its variable, which then locks the field (see
[Settings](settings.md)). A limit goes from 1 to 1000 a minute (100 000 a day, 60 tests a
minute): it can be loosened or tightened, never switched off. A change applies within a few
seconds, without a restart, and starts that limit's counters again.

Beyond a limit, the page for opening an invitation link, and allauth's pages
(signing in, signing up, password reset), answer 429. Sending an invitation, to
a home or to the instance, and erasing an account on the web stay on their page
with a message saying to try again later. The API answers 429 for all of them.

## Which address

The client address is `REMOTE_ADDR`. Behind a reverse proxy it is the address
the proxy reports in `X-Forwarded-For`, and only when the proxy is listed in
`HOUSECAIRN_FORWARDED_ALLOW_IPS`; from any other peer the header is dropped, and
HouseCairn never reads it itself. A client that forges the header does not
change the address it is counted under. See [Reverse proxy](reverse-proxy.md).

## Per process, or shared

The counters live in a cache. The default is in the memory of each web process,
so with `HOUSECAIRN_WEB_WORKERS=2` each process counts alone and a limit can be
up to twice as loose. To share the counters between the web processes, point
`HOUSECAIRN_CACHE_URL` at a shared cache:

```ini
HOUSECAIRN_CACHE_URL=dbcache://housecairn_cache
```

keeps them in the database (the table is created at start-up, with SQLite or
PostgreSQL). A Redis or Memcached URL works as well. The limits still are a
brake: the verification of addresses and the anti-robot check are the other
barriers of open sign-up.
