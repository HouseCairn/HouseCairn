# Release notes

HouseCairn has no release yet. The notes of each version will be published
with it on the project's
[releases page](https://github.com/HouseCairn/housecairn/releases).

## Unreleased

### New

- **Rooms, items and photos.** Describe the rooms of a home, what was used in
  them (the room memory), the equipment and surfaces they hold, and add photos.
  Screens, API and a guide: see [Rooms and items](guides/rooms-and-items.md).
  Photos are stored in `/data/media/photos/`, checked by their content and
  stripped of their metadata. The new variable `HOUSECAIRN_PHOTO_MAX_BYTES` sets
  the size limit of a photo (10 MB by default).

### Upgrade notes

- **Reverse proxy: set `HOUSECAIRN_FORWARDED_ALLOW_IPS`.** HouseCairn used to
  accept forwarding headers (`X-Forwarded-Proto`, `X-Forwarded-For`) from any
  peer. It now accepts them only from the addresses in
  `HOUSECAIRN_FORWARDED_ALLOW_IPS`, by default the container's own loopback
  (`127.0.0.1,::1`). An instance behind a reverse proxy must set it to the
  address or network the proxy connects from; otherwise HouseCairn ignores the
  proxy's headers, every request is redirected to HTTPS again, and every client
  is counted under the proxy's address for the sign-in limits. With the example
  `compose.yaml` and a proxy on the host, the value is `192.0.2.1`, the gateway
  of its now fixed network. See [Reverse proxy](administration/reverse-proxy.md).
