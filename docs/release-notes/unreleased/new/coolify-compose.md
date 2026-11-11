---
orphan: true
nosearch: true
---

- **A Compose file for Coolify.** `deploy/coolify/docker-compose.yaml` runs the same image,
  with the same hardening, as `compose.yaml`, without a published port, an environment
  file or a fixed network range: Coolify's proxy reaches the container, and the domain set
  in Coolify gives `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `HOUSECAIRN_SITE_URL`
  ([Deploy with Coolify](../../../administration/coolify.md)).
