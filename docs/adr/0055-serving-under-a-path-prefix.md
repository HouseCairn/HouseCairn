# 0055. Serving the application under a path prefix

- Status: accepted
- Date: 2026-11-10
- Extends: [0012](0012-configuration-and-security-defaults.md) (trusted proxies),
  [0053](0053-target-navigation-and-return-rule.md) (return rule)

## Context

HouseCairn assumed it was served at the root of a host name: `/` was Today, the cookies
were sent to `/`, the manifest of the installed application had `"scope": "/"`, and the
return rule accepted any `next` that started with `/`. Some proxies serve an application
under a path instead, such as `https://example.com/housecairn/`. Home Assistant's
Ingress, which the Home Assistant add-on will use, serves it under
`/api/hassio_ingress/<token>/`, removes that prefix before passing the request on, and
names it in an `X-Ingress-Path` header; the token is only known at request time.

## Decision

**A variable fixes the prefix.** `HOUSECAIRN_URL_PREFIX` (empty by default) is a path such
as `/housecairn`, checked at start-up: segments of unreserved characters, no `.` nor `..`
segment, no query. It becomes Django's `FORCE_SCRIPT_NAME`, so every address Django builds
(`reverse`, `{% url %}`, static files, redirects, the sign-in page) starts with it, in the web
process and in the task worker, whose reminder emails have no request to read it from. The
session, CSRF and language cookies get it as their path.

**A header may give it per request, only when allowed.** `HOUSECAIRN_URL_PREFIX_HEADER`
names a header, such as `X-Ingress-Path`; it is off unless set. The header counts only from
a trusted proxy (`HOUSECAIRN_FORWARDED_ALLOW_IPS`, [0012](0012-configuration-and-security-defaults.md)):
`ForwardedHeadersMiddleware` removes it from any other peer, with the other forwarding
headers. A value that is not a plain path is ignored. When valid, it replaces the variable
for that request.

**One middleware applies it**, right after the forwarding headers and before anything reads
the path: `core.prefix.UrlPrefixMiddleware` sets the script prefix of the request, accepts
the path with or without the prefix (a proxy that removes it and one that passes it both
work), and limits every cookie of the response to the prefix, including those set by
allauth or the session middleware. Without a prefix, it does nothing.

**The return rule stays as strict.** A `next` must still be a safe path of this host, and
under a prefix it must lead under the prefix once a browser has resolved it: `\` read as
`/`, `%2e` as `.`, then the dot segments removed (`core.prefix.in_application`). The same
check applies to allauth's `next` and to the display preferences. The routes of a `next`
are read without the prefix (`core.prefix.resolve_url`), so labels, breadcrumbs and the
section of the bar work the same.

**Static files.** Django keeps the base URL of the static files storage, and
`settings.STATIC_URL` with its prefix, from the first time they are read; a prefix given by
the header would then be that of the first request. `core.storage` builds the base URL at
each call from the script prefix of the request. WhiteNoise matches the path without the
prefix, so it serves them in both modes.

**What else follows the prefix:** the manifest (`start_url` and `scope`), the API and its
schema (a `servers` entry under a prefix, so clients call the right path), the links of
emails, of QR labels and of calendar feeds (`HOUSECAIRN_SITE_URL` stays scheme and host,
the path comes from `reverse`). The Content Security Policy names origins only (`'self'`);
it is unchanged. `CSRF_TRUSTED_ORIGINS` are origins too: nothing changes there.

**A test keeps it so:** a template or a script that writes an address starting with `/`
fails the suite, and a CI step runs the navigation tests with a prefix set.

## Consequences

- An instance served at the root behaves as before: no setting, cookie or address changes.
- With the header, a link built during a request carries that request's prefix, and a link
  built by the task worker carries `HOUSECAIRN_URL_PREFIX`. An add-on that knows its Ingress
  path at start-up should set the variable as well, so that both agree.
- `*` in `HOUSECAIRN_FORWARDED_ALLOW_IPS` lets any peer set the prefix through the header,
  as it lets any peer set the other forwarding headers.

## Alternatives considered

- **`SCRIPT_NAME` from the WSGI server only.** gunicorn reads it from its environment or
  from a header of a trusted proxy, but refuses a request whose path does not start with
  it, and the task worker never sees it. `FORCE_SCRIPT_NAME` covers both.
- **Building every address sent away on `HOUSECAIRN_SITE_URL` plus the configured prefix,
  whatever the request.** It would change every place that builds one, for a case (header and site
  address together) that the add-on can avoid by setting the variable.
- **Trusting `X-Forwarded-Prefix` by default.** A prefix header is off unless named, so a
  proxy that forwards a client's header unchanged cannot move the application.
