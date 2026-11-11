---
orphan: true
nosearch: true
---

- **The backup of the instance leaves the secret key out.** `backup_instance` no longer puts
  `/data/secret_key` in the archive: with the key, a copy of the archive gave every stored
  secret. Keep the key apart, best as `SECRET_KEY` in `deploy/production.env`, and add
  `--include-secret-key` if a backup must restore alone. A restore without the key says what
  to do ([Data and backups](../../../administration/backup.md#the-secret-key),
  [ADR 0060](../../../adr/0060-secret-key-apart-from-the-backups.md)).
- **Notification channels on a private network are refused unless allowed.** Addresses of
  private networks (such as a ntfy or a Gotify on the local network) are no longer sent to
  by default, and their test says why. If your people use one, turn on **Channels on the
  local network** in **Instance administration, Settings, Notifications**, or set
  `HOUSECAIRN_NOTIFICATIONS_PRIVATE_NETWORKS=true`
  ([Hardening](../../../administration/hardening.md),
  [ADR 0059](../../../adr/0059-notifications-refuse-private-networks.md)).
