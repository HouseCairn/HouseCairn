---
orphan: true
nosearch: true
---

- **Served under a path prefix.** An instance can live under a path, such as
  `https://example.com/housecairn/`, with `HOUSECAIRN_URL_PREFIX`: pages, static files,
  cookies, the installed application, the API and the links of emails, QR labels and
  calendar feeds follow it. A trusted proxy can also give the prefix of each request in a
  header named by `HOUSECAIRN_URL_PREFIX_HEADER`, as Home Assistant's Ingress does. See
  [Serving under a path prefix](../../../administration/url-prefix.md).
