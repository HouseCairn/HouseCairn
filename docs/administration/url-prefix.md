# Serving under a path prefix

HouseCairn can be served under a path, such as `https://example.com/housecairn/`,
instead of at the root of a host name. Everything follows the prefix: the pages,
the static files, the cookies, the installed application, the API and the links of
emails, QR labels and calendar feeds.

## A fixed prefix

Set the prefix in `deploy/production.env`:

```ini
ALLOWED_HOSTS=example.com
CSRF_TRUSTED_ORIGINS=https://example.com
HOUSECAIRN_SITE_URL=https://example.com
HOUSECAIRN_URL_PREFIX=/housecairn
```

- `HOUSECAIRN_URL_PREFIX` is a path: it starts with `/`, and its segments hold letters,
  digits and `. _ ~ -`. A trailing slash is ignored. HouseCairn refuses to start with
  any other value.
- `HOUSECAIRN_SITE_URL` and `CSRF_TRUSTED_ORIGINS` stay a scheme and a host, without
  the prefix: HouseCairn adds it to the links it builds.
- The cookies of HouseCairn are limited to the prefix: another application on the same
  host name does not receive them.

The proxy may pass the path with the prefix or remove it: both work. With Caddy:

```text
example.com {
    handle /housecairn* {
        reverse_proxy 127.0.0.1:8000
    }
}
```

With nginx:

```nginx
    location /housecairn/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
```

The [reverse proxy](reverse-proxy.md) settings stay the same:
`HOUSECAIRN_BEHIND_TLS_PROXY` and `HOUSECAIRN_FORWARDED_ALLOW_IPS`. The health check of
the container keeps calling `/healthz` directly.

## A prefix given by the proxy

Some proxies only know the prefix when the request arrives, and send it in a header.
Home Assistant's Ingress, for example, serves an add-on under
`/api/hassio_ingress/<token>/` and sends that path in `X-Ingress-Path`. Name the header:

```ini
HOUSECAIRN_URL_PREFIX_HEADER=X-Ingress-Path
HOUSECAIRN_FORWARDED_ALLOW_IPS=192.0.2.10
```

- The header is ignored unless `HOUSECAIRN_URL_PREFIX_HEADER` names it.
- It counts only from the addresses of `HOUSECAIRN_FORWARDED_ALLOW_IPS`; from any other
  peer, HouseCairn removes it before reading the request. With `*`, any peer that reaches
  the container can set it.
- A value that is not a plain path is ignored. A valid value replaces
  `HOUSECAIRN_URL_PREFIX` for that request.
- The pages, forms and static files follow the prefix of the header, since the browser is
  behind that proxy. The cookies are limited to it.

## Links sent away

A link made to leave HouseCairn is always built on the public address:
`HOUSECAIRN_SITE_URL`, then `HOUSECAIRN_URL_PREFIX`, never the prefix of the request. This
covers the links of emails (invitations, password reset, address verification, reminders,
report alerts), the address a QR label holds, the address of a calendar feed and the links
of its events, and the address of the first-account screen written in the log.

A prefix given by a header only works through that proxy: an Ingress path, for example, only
opens inside Home Assistant's interface, and its token changes. Behind such a proxy, set
`HOUSECAIRN_SITE_URL` to an address that reaches HouseCairn without it, if you have one, and
`HOUSECAIRN_URL_PREFIX` to the path of that address.

Without `HOUSECAIRN_SITE_URL`, the links built during a request (invitations, password reset
and address verification emails, QR labels, calendar feeds) take the scheme and host of the
request, with `HOUSECAIRN_URL_PREFIX`. Reminders and report alerts, sent by the task worker,
then carry no link, and the first-account address in the log is a path only.

## In a frame of the same site

By default, no page may show HouseCairn in a frame (`X-Frame-Options: DENY`, Content
Security Policy `frame-ancestors 'none'`). A proxy that shows it in a frame of its own page,
on the same scheme, host and port, as Home Assistant's Ingress panel does, needs:

```ini
HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING=true
```

The headers become `X-Frame-Options: SAMEORIGIN` and `frame-ancestors 'self'`; a page of any
other origin still cannot frame it. The value is `true` or `false`; HouseCairn refuses to
start with any other.

Behind Ingress, HouseCairn keeps its own sign-in: it does not sign anyone in from the Home
Assistant user that the Supervisor names in its headers.

## Installed application

The manifest and the service worker follow the prefix: the installed application opens
`/housecairn/`, and its service worker serves and keeps only addresses under it. Its caches
are named after the prefix, so two applications under two prefixes of the same host never
share nor delete each other's data. Nothing is to configure.

## What stays the same

The address of each page after the prefix is the same as at the root, so is the API:
`/housecairn/api/v1/...`, and the schema at `/housecairn/api/schema/` gives it in its
`servers` entry. A `next` address, which brings you back to the screen you came from,
is refused when it leads outside the prefix.
