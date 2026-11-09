# Release notes

HouseCairn has no release yet. The notes of each version will be published
with it on the project's
[releases page](https://github.com/HouseCairn/housecairn/releases).

## Unreleased

### New

- **Calendar and calendar feeds.** See your tasks by week, month or year, with filters by home,
  room, person and priority, **Done** and **Undo** in place, and the next dates of a task that
  repeats marked as forecast. **Feeds** gives a secret address per home, or for all your homes,
  that Google Calendar, Apple Calendar, Thunderbird or Home Assistant can subscribe to: it shows
  titles, home, room, date and status, never notes, costs or files. You can get a new address or
  revoke it at any time; leaving a home revokes your feed of it. See
  [Calendar](screens/calendar.md) and [Calendar and feeds](guides/calendar.md). New dependency:
  `icalendar`.
- **Reports.** Every member of a home, a read-only one included (a tenant, a tradesman), can
  **Report a problem** with a title, a place and a photo, from a form or from a scanned
  sticker. Members who may write see the open reports on Today, make one into a task, close
  it or reopen it, and are told on their notification channels; the person who reported
  keeps a list of their own reports and sees nothing of the others. Reports are in the API,
  in the export of a home and are erased with it. See [QR labels and reports](guides/qr-labels.md)
  and [ADR 0047](adr/0047-qr-labels.md).
- **QR labels.** Print stickers that open a room, an item or a stock item: a PDF made by
  the server, as an A4 sheet of 3 by 8 labels or a 62 mm roll for a label printer. The
  code on a sticker is a random identifier of 128 bits that names nothing; a sticker
  opens the page of the object for the members of the home and answers the same "Page
  not found" to everyone else, and it can be revoked or replaced. Labels are in the API,
  in the export of a home and are erased with it. Set `HOUSECAIRN_SITE_URL` before
  printing: the address is on the stickers. See [QR labels](guides/qr-labels.md). New
  dependency: ReportLab ([ADR 0047](adr/0047-qr-labels.md)).

- **Budget.** A new **Budget** tab shows the money of a home by room, by project and for the
  upkeep: planned, committed, paid and the gap, in words and with labelled gauges, for the
  envelope of a year, by nature, by year and over the last 12 months. A task now shows its
  cost, with what it comes to in a year when it repeats. Several homes are added up by
  currency, never converted. Every page downloads as CSV, and the API has the same figures
  (read only). Amounts are typed the same way everywhere, with the comma in French: see
  [Budget](guides/budget.md) and [Entering an amount](guides/amounts.md). Nothing new is
  stored, so there is nothing more to export or erase. *Still to pay* on a project is now
  worked out line by line, as the gap is.

- **Notifications.** Each person adds their own channels (ntfy, Telegram, Signal, Matrix,
  Gotify, email and other Apprise services) on **More, Notifications**, tests them, and
  chooses when reminders come: days before the due date, time of day, quiet hours, a daily
  summary. Follow-ups come until the task is done, skipped or postponed, more often for a
  high priority. Addresses are encrypted and never shown again. Off by default: an
  administrator turns them on with `HOUSECAIRN_NOTIFICATIONS_ENABLED` or in the settings.
  See [Notifications](guides/notifications.md).

- **Verify an address from the server.** On an instance that sends no email, `manage.py
  verify_email <address> [--primary]` marks an account's address verified, so that the account
  can accept an invitation handed over by hand. It is recorded in the audit log of the
  instance. See [Email](administration/email.md).

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

- **Projects and quotes.** Plan a piece of work such as redoing the bathroom: a project
  with a status, a priority, rooms, a duration and a season, its steps as tasks created
  inside it, quotes from contractors, and a budget of lines with a planned, a committed
  (the quotes you accept) and a paid amount, whose gap is said in words. Compare projects
  side by side and set a budget envelope for the year. Screens, API and a guide: see
  [Projects and quotes](guides/projects.md). Photos and quote files are stored in
  `/data/media/projects/` and are part of the export of the home. Add links of inspiration to
  a project; if the administrator turns on **Preview of inspiration links** (off by
  default), the server reads each page once, when the link is added, for its title and its
  picture, which it keeps and serves itself. Only public web addresses are read: private
  networks and cloud metadata services are refused, on every redirect, with limits on size
  and time.

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

- **Seasons, display name, duration and contractors.** A task can be limited to a predefined
  season (spring, summer, autumn, winter or the heating season) that follows the hemisphere
  of the home, which you set on the home page, or to custom months; existing windows become
  the matching season or a custom one. Each person can choose a display name on the new
  [profile](screens/profile.md) screen and in the API (`/api/v1/me/`), and the person in
  charge is shown by that name on every page, never by an address. The estimated duration
  is a number and a unit (minutes, hours, days). A task has a single contractor field, and
  each contractor has a [sheet](screens/contractor.md): trade from a list (plus Other),
  phone, email address, address, note and the tasks that name them, downloadable as a
  contact file (.vcf). Existing trades are matched to the list, otherwise kept under Other.
  See [Tasks and recurrence](guides/tasks-and-recurrence.md).

- **The stock follows the tasks and the rooms.** A task lists the stock items it needs, with
  a quantity (the **Materials** section of its form and its page, and `task-materials` in the
  API). Marking the task **Done** takes them from the stock, in the same gesture; **Undo**
  puts them back with new entries, nothing is erased from the ledger; the quantity really
  used is entered afterwards in the details of what was done. **Done** is never refused for
  lack of stock: the stock stops at zero and a message (`short` in the API) says what was
  missing. A room shows the stock items that concern it, and its paint left over is a link
  to a stock item, with its quantity and place. The unit of a stock item is a list (piece,
  litre, metre, kilogram, roll, box) plus Other. See [Stock and supplies](guides/stock.md),
  [Tasks and recurrence](guides/tasks-and-recurrence.md) and
  [ADR 0046](adr/0046-stock-linked-to-tasks-and-rooms.md).
- **Display name from the sign-in provider.** An account linked to a single sign-on provider
  takes its display name from the provider at each sign-in through it (`name`, else the
  given and family names, the username or the nickname), by the same rules as a typed name;
  a claim that would be refused is ignored and never stops the sign-in. A name typed on the
  [profile](screens/profile.md) is kept and no provider overwrites it, until **Use the
  provider's name**. Display names typed before this version are kept; accounts without one
  take the provider's at their next sign-in. See
  [Single sign-on](administration/oidc.md#display-name).

### Fixed

- **Display preferences in the API.** Changing one preference no longer fails because the
  stored language is one the instance no longer ships: only the fields sent are checked.
- **Hidden text in names and titles.** Tag characters that spell a regional flag stay
  only inside the flag, joiners stay only between two visible characters, and the line and
  paragraph separators go; a name made only of such characters is empty, not invisible.
- **Room names in the API.** A room created or changed with an empty or invisible name takes
  the label of its type, as on the screen, instead of an error.

- **Return addresses with a control character.** A `next` address such as `//` followed by
  a line break or a tab was accepted after sign-in and sent to the browser as `//%0D`, an
  address whose host browsers refuse: the redirect failed. Every `next` (sign-in, sign-up,
  invitations, display preferences, task buttons) now refuses a control or space character
  and an address that starts with `//` or `\`, and falls back to the default page.

### Upgrade notes

- **The paint left in stock and the unit of a stock item change shape.** The field
  `paint_stock` of a room is replaced by `paint_article` (a stock item of the home); the
  old text is kept, word for word, as a line `Paint left in stock: ...` of the memory
  notes, which can then exceed the 4,000 characters usual for notes until it is shortened.
  `unit` of a stock item now accepts the codes of the list (`piece`, `litre`, `metre`,
  `kilogram`, `roll`, `box`, `other`) with `unit_other`; usual spellings (pieces, litres,
  kg, rouleau) become the matching code, anything else is kept under Other. Both migrations
  are reversible: going back writes the text again (the plural of the list for a unit).
  Clients of the API must use the new names.

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
