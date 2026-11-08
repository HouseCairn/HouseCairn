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

- **Instance settings in the interface.** Sign-up, invitations, outgoing email and the
  public address can be changed by an instance administrator, in the interface and by the
  API, each paired with its environment variable: a variable that is set wins and locks the
  field. Secrets are encrypted in the database. See [Settings](administration/settings.md).

- **Sign-in providers in the interface.** An instance administrator can declare OpenID
  Connect providers on **Instance administration, Sign-in providers**, or by the API, next to
  the one the `OIDC_*` variables set, which stays read only. A **Test the issuer** button
  reads the provider's configuration. The administrator cannot remove their own last way to
  sign in, and the only administrator cannot be switched off in the administration site. See
  [Single sign-on](administration/oidc.md).

- **Stock.** Keep track of spare parts and supplies: items with a threshold, suppliers
  and an append-only ledger of movements from which the quantity is computed, a photo of
  the label, and the equipment each item fits. Screens, API and a guide: see
  [Stock and supplies](guides/stock.md). Label photos are stored in `/data/media/stock/`.

### Upgrade notes

- **Environment variables are checked a little more strictly.** A boolean variable such as
  `HOUSECAIRN_SIGNUP_OPEN` or `EMAIL_USE_TLS` must be `true` or `false` (also `1`, `0`, `yes`,
  `no`, `on`, `off`); another word used to count as `false` and now stops the start-up with a
  message. `EMAIL_PORT` and `EMAIL_TIMEOUT` must be in range, and the domain lists must hold
  domain names. A variable set to an empty value now counts as not set.

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
