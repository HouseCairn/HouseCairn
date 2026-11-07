# Update

1. Read the [release notes](../release-notes.md) of the new version.
2. [Back up](backup.md) `/data`.
3. Change the tag (and digest) in `compose.yaml`,
   [verify the new image](../security/verify-image.md), then:

   ```sh
   docker compose pull
   docker compose up -d
   ```

Migrations run at start. Going back to an older version after its migrations
have run needs the backup.

## Tags

| Tag | Points to |
| --- | --- |
| `X.Y.Z` | A release. |
| `X.Y` | The most recently published `X.Y.*` release. |
| `latest` | The most recently published release (never a pre-release). |
| `X.Y.Z-rc.N` | A pre-release. |
| `edge` | The latest commit on `main`: for testing, not for production. |
| `sha-<commit>` | The image built from that commit. |

Pin a version and its digest in production; a tag can move, a digest cannot.
