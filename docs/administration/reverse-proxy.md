# Reverse proxy

HouseCairn listens on plain HTTP and expects a reverse proxy to terminate
HTTPS in front of it. With the example `compose.yaml`, it listens on
`127.0.0.1:8000` of the host.

In `deploy/production.env`, for an instance at `housecairn.example.com`:

```ini
ALLOWED_HOSTS=housecairn.example.com
CSRF_TRUSTED_ORIGINS=https://housecairn.example.com
HOUSECAIRN_BEHIND_TLS_PROXY=true
```

`HOUSECAIRN_BEHIND_TLS_PROXY=true` makes HouseCairn trust the
`X-Forwarded-Proto` header: set it only when the proxy sets that header itself
and the container cannot be reached without the proxy. Without it, HouseCairn
sees plain HTTP and redirects every request to HTTPS.

## Caddy

Caddy obtains the certificate and sets `X-Forwarded-Proto` by default:

```text
housecairn.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

## nginx

```nginx
server {
    listen 443 ssl;
    server_name housecairn.example.com;
    # ssl_certificate and ssl_certificate_key of your certificate.

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

HouseCairn sets its own security headers (Content Security Policy, HSTS,
`X-Frame-Options`); the proxy does not need to add them.
