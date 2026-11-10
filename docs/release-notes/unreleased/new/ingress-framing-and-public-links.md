---
orphan: true
nosearch: true
---

- **Behind Home Assistant's Ingress.** `HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING=true` lets a page
  of the same origin show HouseCairn in a frame, as the Ingress panel does; it is off by
  default. Links made to leave the application (emails, invitations, QR labels, calendar
  feeds) are now always on `HOUSECAIRN_SITE_URL` and `HOUSECAIRN_URL_PREFIX`, never on a
  prefix given by a proxy header. See
  [Serving under a path prefix](../../../administration/url-prefix.md).
