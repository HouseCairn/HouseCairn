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

Housecairn makes no outgoing connection unless you configure one (single
sign-on, later the integrations), and sends no telemetry.
