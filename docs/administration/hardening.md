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
server call the addresses it types, your local network included, since a self-hosted
ntfy or Gotify lives there. The server only speaks the protocols of the services it
offers (no generic webhook, no header or field added by the address), refuses itself,
link-local addresses and the metadata services of cloud providers, gives up after eight
seconds per channel and then cuts the connections of that send, so that a slow server
holds no thread or connection of the instance, and allows five tests a minute per person;
each test tells the person only whether the message was sent. If your local network holds services that must not
receive such calls, leave notifications off, or keep the server out of that network.
