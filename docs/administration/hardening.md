# Hardening

`compose.yaml` runs the container the recommended way:

| Setting | Effect |
| --- | --- |
| `read_only: true` | The image's file system cannot be modified. Only `/data` and `/tmp` are writable. |
| `tmpfs: /tmp` | Temporary files (large uploads in progress) stay in memory, 64 MB at most, and disappear at restart. |
| `cap_drop: [ALL]` | No Linux capability: the application needs none. |
| `security_opt: no-new-privileges:true` | No process can gain privileges, even through a set-user-ID binary. |
| user `10001:10001` | Set in the image; the application never runs as root. |

The same settings with `docker run`:

```sh
docker run -d --name housecairn \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges \
  --env-file deploy/production.env \
  -v housecairn-data:/data -p 127.0.0.1:8000:8000 \
  ghcr.io/housecairn/housecairn:X.Y.Z
```

`/healthz` answers `{"status": "ok"}` without authentication and reveals
nothing else; the image's `HEALTHCHECK` calls it.

HouseCairn makes no outgoing connection unless you configure one (single
sign-on, notifications, later the integrations), and sends no telemetry.

Turning [notifications](../guides/notifications.md) on lets every account make the
server call the addresses it types. The server only speaks the protocols of the services
it offers (no generic webhook, no header or field added by the address), refuses itself,
link-local addresses and the metadata services of cloud providers, and checks the address
of every connection a send opens, gives up after eight seconds per channel and then cuts
the connections of that send, so that a slow server holds no thread or connection of the
instance, and allows five tests a minute per person; each test tells the person only
whether the message was sent, or that its address is on a private network.

**Private networks are refused by default**: the private networks of RFC 1918, the
shared address space `100.64.0.0/10`, IPv6 unique local addresses `fc00::/7`, and every
other address that is not public. A self-hosted ntfy or Gotify on
your local network needs **Channels on the local network**
(`HOUSECAIRN_NOTIFICATIONS_PRIVATE_NETWORKS=true`). Turned on, every account can make the
server call a private address, with the requests of one of the services above, and learn
whether it answered: if your local network holds services that must not receive such
calls, leave it off, and reach your ntfy or Gotify by a public address, or keep the
server out of that network ([ADR 0059](../adr/0059-notifications-refuse-private-networks.md)).

**Notifications on the device** (`HOUSECAIRN_WEBPUSH_ENABLED`, off by default) go through
the push service of each browser, which the browser chooses: Google (Firebase Cloud
Messaging, for Chrome, Edge, Brave, Opera, Samsung Internet), Mozilla (Firefox), Apple
(Safari) or Microsoft. Some of them are outside the EU. Each message is encrypted for the
device (RFC 8291): the push service sees the address of the device, when a message is sent
and its size, not what it says. The server only posts to these four services, over HTTPS
on port 443, to public addresses, and gives up after eight seconds. With **Discreet
notifications on the device** (`HOUSECAIRN_WEBPUSH_DISCREET`, on by default) a notification
says only that a task is due or a problem was reported, so nothing of a home shows on a
locked screen ([ADR 0066](../adr/0066-notifications-on-the-device-by-web-push.md)).
