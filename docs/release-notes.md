# Release notes

HouseCairn has no release yet. The notes of each version will be published
with it on the project's
[releases page](https://github.com/HouseCairn/housecairn/releases).

## Unreleased

### New

- **QR labels.** Print stickers that open a room, an item or a stock item: a PDF made by
  the server, as an A4 sheet of 3 by 8 labels or a 62 mm roll for a label printer. The
  code on a sticker is a random identifier of 128 bits that names nothing; a sticker
  opens the page of the object for the members of the home and answers the same "Page
  not found" to everyone else, and it can be revoked or replaced. Labels are in the API,
  in the export of a home and are erased with it. Set `HOUSECAIRN_SITE_URL` before
  printing: the address is on the stickers. See [QR labels](guides/qr-labels.md). New
  dependency: ReportLab ([ADR 0047](adr/0047-qr-labels.md)).

- **Notifications.** Each person adds their own channels (ntfy, Telegram, Signal, Matrix,
  Gotify, email and other Apprise services) on **More, Notifications**, tests them, and
  chooses when reminders come: days before the due date, time of day, quiet hours, a daily
  summary. Follow-ups come until the task is done, skipped or postponed, more often for a
  high priority. Addresses are encrypted and never shown again. Off by default: an
  administrator turns them on with `HOUSECAIRN_NOTIFICATIONS_ENABLED` or in the settings.
  See [Notifications](guides/notifications.md).

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
  reads the provider's configuration. A new issuer clears the client secret unless it is
  entered again. The administrator cannot remove nor change their own last way to sign in,
  and the only administrator cannot be switched off in the administration site. See
  [Single sign-on](administration/oidc.md).

- **Rate limits, quotas, language, time zone and name of the instance.** An instance
  administrator can change the rate limits, the quotas of files of each home, the default
  language, the time zone and the name of the instance in the interface, each paired with
  its variable like the other settings. Quotas apply to every way to add a photo, an
  attachment or a label, and **Files of the homes** shows what each home takes, without its
  content. See [Settings](administration/settings.md).

- **Stock.** Keep track of spare parts and supplies: items with a threshold, suppliers
  and an append-only ledger of movements from which the quantity is computed, a photo of
  the label, and the equipment each item fits. Screens, API and a guide: see
  [Stock and supplies](guides/stock.md). Label photos are stored in `/data/media/stock/`.

- **Feedback from the first tests.** Each person can choose their language in the display
  preferences; the sub-navigation of the tasks, of a home and of the instance administration
  is one set of tabs; the audit log of a home now records what people do to rooms, items,
  tasks, photos and files, by title only, and explains itself when it is empty; a room is
  created from its type, which fills in the name; the room memory explains each field; the
  photos of a room are one list with a category (general, behind the walls, before, after,
  other) that can be filtered; the brand of an item suggests the brands already entered in
  the home, and its maintenance contract is a provider and a number. See
  [Display preferences](screens/display-preferences.md), [Room](screens/room.md) and
  [Audit log of a home](screens/audit.md).

### Fixed

- **Return addresses with a control character.** A `next` address such as `//` followed by
  a line break or a tab was accepted after sign-in and sent to the browser as `//%0D`, an
  address whose host browsers refuse: the redirect failed. Every `next` (sign-in, sign-up,
  invitations, display preferences, task buttons) now refuses a control or space character
  and an address that starts with `//` or `\`, and falls back to the default page.

### Upgrade notes

- **Photo categories and the contract of an item change shape.** The category `open_walls`
  of a photo is now `behind_walls`, in the API and in exports; the field `contract` of an
  item is now `contract_provider` (the old text, whole) and `contract_number`, in the API
  and in exports. The migrations are reversible, but going back joins the two into the one
  text again and cuts it at 200 characters: the contract number is lost when the provider
  alone is longer than that. Clients of the API must use the new names.

- **Each home now has quotas of files**: 5 GB and 5000 files by default, deleted files
  included until they are purged. Raise them in **Instance administration, Settings, Files of
  a home**, or with `HOUSECAIRN_HOME_STORAGE_MB` and `HOUSECAIRN_HOME_MAX_FILES`.
  `HOUSECAIRN_PHOTO_MAX_BYTES` and `TIME_ZONE` keep their meaning; set, they lock their field.

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
