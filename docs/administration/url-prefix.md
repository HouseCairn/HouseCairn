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
- Reminder emails are sent by the task worker, which sees no request: their links use
  `HOUSECAIRN_URL_PREFIX`. Set it too when the prefix is known at start-up.

## What stays the same

The address of each page after the prefix is the same as at the root, so is the API:
`/housecairn/api/v1/...`, and the schema at `/housecairn/api/schema/` gives it in its
`servers` entry. A `next` address, which brings you back to the screen you came from,
is refused when it leads outside the prefix.
