---
orphan: true
nosearch: true
---

- **The 400 page of a refused host name says what to do.** An address that is not in
  `ALLOWED_HOSTS` gets a page that tells the administrator to add the name. Whoever hosts
  HouseCairn for someone else can name the exact option with
  `HOUSECAIRN_DISALLOWED_HOST_HINT`; the page never repeats the refused name
  ([settings](../../../administration/settings.md#the-page-of-a-refused-host-name)).
