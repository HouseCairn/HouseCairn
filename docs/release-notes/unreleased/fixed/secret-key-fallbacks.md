---
orphan: true
nosearch: true
---

- **Rotating the secret key keeps the stored secrets.** `SECRET_KEY_FALLBACKS`, which the
  documentation advised for a rotation, was not read: the SMTP password, the secrets of
  the sign-in providers and the notification channels became unreadable with the new key.
  It is now read, comma-separated, and the steps are in
  [Rotate the key](../../../administration/settings.md#rotate-the-key).
- **Every connection of a notification is checked.** While a message is sent, the address
  of each connection is checked as the names were, IPv4, IPv6 and IPv4 in IPv6, so a
  service that would skip name resolution reaches no refused address either
  ([ADR 0059](../../../adr/0059-notifications-refuse-private-networks.md)).
