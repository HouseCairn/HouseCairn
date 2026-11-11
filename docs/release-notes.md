# Release notes

The notes of each version are also published with it on the project's
[releases page](https://github.com/HouseCairn/housecairn/releases).

## Unreleased

### New

```{release-fragments} new
```

### Fixed

```{release-fragments} fixed
```

### Upgrade notes

```{release-fragments} upgrade
```

## 0.1.0

The first version of HouseCairn. It is a test version: it has not been used in a
real home for any length of time yet, and what it stores can still change shape
from one 0.x version to the next, with the upgrade notes of each version saying
what to do. The entries below were written along the development. The upgrade
notes concern instances that ran an image built from `main` (`edge` or
`sha-<commit>`) before this version; a new instance has nothing to do.

### New

- **Longer estimated durations, and a contractor chosen in a list.** The estimated duration
  of a task takes weeks, months and years as well as minutes, hours and days, up to one
  year instead of thirty days (a week is 7 days, a month 30 days, a year 365 days), and the
  number is readable next to its unit on a phone. The contractor of a task is chosen in the
  list of the contractors of the home; its last choice, **Add a contractor…**, adds one
  (name and trade) without leaving the form, with or without script
  ([task form](screens/task-form.md)).

- **Done without losing your place.** On [Today](screens/today.md) and in
  [all the tasks](screens/tasks.md), **Done** no longer reloads the page nor sends
  it back to the top: the row shows the task as done, and a banner at the bottom of the
  screen, above the bar, offers **Undo**, announced by screen readers. Without
  JavaScript, the page comes back to the row. The browser's back button no longer shows
  an old **Undo** banner, and going back to a creation form no longer creates the
  record twice.

- **API tokens for a home that requires a sign-in provider.** Such a home can now be given
  to a token, for example for Home Assistant, from a session signed in through its
  provider: on the [API tokens](screens/api-tokens.md) form, it is listed and
  **Continue with** the provider unlocks it. The token remembers the provider, and stops
  opening the home if an owner requires another one. **Create a token** is shown as soon
  as you belong to a home.

- **API tokens from the application.** You create, list and revoke your
  [API tokens](screens/api-tokens.md) in **More**, **API tokens**, without a command
  on the server: a name, the rights (**Read** by default), the homes it opens and an expiry
  of 30 days, 90 days (the default) or 1 year. The value is shown once, with a **Copy**
  button, and never again. The same operations are in the
  [API](api/index.md): `GET` and `POST /api/v1/me/tokens/`, `DELETE
  /api/v1/me/tokens/<id>/`, for a person signed in only (a token gets `403`). Creating and
  revoking a token go to the audit log of the instance.

- **Tasks without a date in the API.** `GET /api/v1/homes/<id>/tasks/?due=none` returns only
  the active tasks that have no due date, so an integration no longer has to read the whole
  list to find them. It combines with the other filters and with the cursor; any other value
  of `due` is a 400. See the [API guide](api/index.md).

- **Import tables from CSV files.** Owners and members add rooms, items, tasks, stock and
  contractors to a home from the CSV files of **Tables for a spreadsheet**, edited in a
  spreadsheet: the preview shows each row accepted or refused with the reason and writes
  nothing, then **Import** adds every row in one go, all or nothing: while a single row is
  refused, nothing is imported. At most 1,000 rows and 2 MB per import. A row already in
  the home is refused, never merged, and a reference to another home is refused. The API does the
  same with `POST /api/v1/homes/<id>/import/` and a token with the `write` scope
  ([Import tables](screens/home-import.md)).
- **Opening a table in Excel or LibreOffice** is explained step by step, French menus
  included: every CSV of HouseCairn stays separated by commas
  ([Export and deletion](administration/data.md#opening-a-table-in-a-spreadsheet)).

- **Current home.** With two homes or more, the app bar shows the current home with a
  selector, and **Rooms**, **Projects**, **Budget** and **Today** open on it instead of
  asking which home at each change of section. Today and the calendar also offer
  **All homes**, where each row names its home. The current home is a preference of
  the session, never a permission: only your own homes are listed, and a home you
  leave is replaced by another ([the current home](screens/my-home.md#the-current-home)).
- The **Budget** entry opens the budget of the current home.

- **Design guide completed.** The [design guide](developer/design-guide.md)
  now says where the list of a new type of data goes, how dates, reminders and alerts
  reuse what tasks already do, what the default parent of a record reachable from two
  places is, and what a new screen must test. The repository also has an `AGENTS.md`
  for coding agents, which points to the contribution rules.

- **Design guide for contributors.** The [design guide](developer/design-guide.md)
  sets the rules every new or changed screen follows: the five sections and their
  tabs, where a screen goes, the return rule, actions in place, the current home and
  the visual system, with a checklist for review. The decision is
  [ADR 0053](adr/0053-target-navigation-and-return-rule.md); the navigation
  prototype and the v2 mock-up are in the repository, under `design/`.

- **Restore a home.** **Homes > Restore a home** makes the archive of **Export all data**
  a new home, on this instance or another, with every room, task, history, stock item,
  project and file, under the same identifiers. A changed, foreign or unsafe archive is
  refused with the reason, and nothing is written
  ([Export and deletion](administration/data.md)).
- **Tables for a spreadsheet.** Every member downloads the rooms, items, tasks, history,
  stock, contractors and reports of a home as CSV files that Excel opens with their
  accents, and that cannot run a formula.
- **Large homes are exported in the background**, then downloaded from the page of the
  export, at most three times within a day.
- **Back up the whole instance in one command**, `backup_instance`, and restore it with
  `restore_instance`, which checks every part first. With PostgreSQL, whose `pg_dump` the
  image does not contain, the guide gives the commands of the `postgres` service instead
  ([Data and backups](administration/backup.md)).

- **First administrator on a web screen.** While an instance has no administrator,
  HouseCairn writes a one-time code in its log at each start. The
  [first-account screen](screens/first-account.md) (`/setup/`) takes that code, a
  name, an address and a password, creates the administrator and signs them in, without
  a command on the server. The code is random, works once and expires after one hour;
  the screen answers 404 as soon as an administrator exists, or when
  `HOUSECAIRN_SETUP_SCREEN=false`. Single sign-on and `createsuperuser` work as before; the
  first one to create an administrator closes the others. See
  [First start](getting-started/first-start.md).

- **Behind Home Assistant's Ingress.** `HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING=true` lets a page
  of the same origin show HouseCairn in a frame, as the Ingress panel does; it is off by
  default. Links made to leave the application (emails, invitations, QR labels, calendar
  feeds) are now always on `HOUSECAIRN_SITE_URL` and `HOUSECAIRN_URL_PREFIX`, never on a
  prefix given by a proxy header. See
  [Serving under a path prefix](administration/url-prefix.md).

- **Instance settings in sections.** The settings of the instance are no longer one long page with
  nine Save buttons: **Instance administration, Settings** is now an index, and each section (public
  address, sign-up, outgoing email, rate limits and the others) has its own page with one button
  that names what it saves. A variable still locks its field and shows the value in force. The old
  addresses, `/instance/settings/?section=<section>`, open the page of the section. See [Instance
  settings](screens/instance-settings.md).

- **Breadcrumbs on a computer.** From 56 rem wide, a record or a form shows the path
  from its section down to the page (Rooms › Living room › Boiler). A phone keeps the
  back link alone.
- **One word per thing.** Screens, buttons and tabs use the same term for the same
  thing, in English and in French. The two audit logs say whether they are about the
  home or the instance, the filter of finished tasks agrees with "tasks" in French, and
  the administration of the instance fits in four tabs.
- **Repeat opens by itself** when a task is created from an item.

- **Five sections in the navigation.** The bar at the bottom of a phone now
  holds Today, Rooms, Projects, Budget and More; on a computer the column on the
  left shows the four sections with the content of More unfolded under them. Each
  section has its own tabs, all visible on a phone: Today, All and Calendar;
  Rooms and Stock; In progress, Ideas and Finished; Summary, Rooms, Projects and
  Upkeep. The history is the **Done** filter of All, and its former address
  leads there. The root of a section has no back link, and the entry marked as
  current is that of the section the page belongs to: Budget marks Budget. More
  comes in four groups, Home, Me, Instance and Help; deleting your account is at
  the bottom of the new [Security and sign-in](screens/security-and-sign-in.md)
  page.

- **One home page: Today.** The logo, signing in and the installed application now
  all open on Today: your only home, or all your homes together if you have
  several. "My home" is gone as a separate screen and its old address redirects. The
  welcome page stays for visitors and for accounts with no home. **Report a problem**
  is under the title of Today for every member, a read-only one included, and the
  number of reports that wait is shown next to **Reports** in More.

- **Repetition in one sentence.** The task form says the repetition as you would: **Repeat
  every** 3 months, **Count from** the due date (with the calendar of the device) or the day
  it is done, and a summary in plain words that follows what you type ("Next time: 3 months
  after the last time"). The fields a choice does not use are hidden, the months of a
  custom season among them; without script they stay visible and are ignored. See the
  [task form](screens/task-form.md).

- **Back to where you came from, everywhere.** Stock, Projects, Budget, Reports, QR labels
  and the pages of a home follow the same rule as Rooms and Tasks: the link at the top
  leads back to the screen a page was opened from, and names it. A project opened from
  the budget says **Budget**, and Budget stays marked in the bar. A stock movement, the
  status of a quote or a button of a report keeps that way back.
- **The budget of a room.** The page of a room shows what is planned and used for it this
  year, with a link to its detail in Budget. In Budget, a room of the budget by room opens
  that detail, project by project and task by task, with **Open the room**.

- **Back to where you came from.** In Rooms and Tasks, the link at the top of a
  page leads back to the screen it was opened from, and names it: a task opened
  from an item goes back to the item. A task or an item added from a room or an item
  comes back to it, with **Added · Open** to open the new record; added from the
  list of its own section, the new record opens. A deletion never leads back to
  the page of what was deleted. The pages of More no longer show a link back to More on a
  computer, where the column already shows it.

- **Task templates.** About twenty common tasks of a home come ready, in English and in
  French, each with an indicative interval and the public source it comes from: the
  battery of the smoke alarms, the service of the boiler, the sweeping of the chimney, the
  vents of the ventilation, the gutters, the hot water tank and more. **Tasks › Add from a
  template** adds them in two taps, and the equipment ticked when a home is created adds
  theirs. A rule of one country, such as the yearly service of a boiler in France, is
  shown as such ([Add from a template](screens/task-templates.md)).
- **A guide of the API**, with `curl` commands that the tests run against an instance:
  token, reads, writes, pages of a list and errors ([Using the API](api/guide.md)).

- **Design guide: a secret is shown once.** The rule that the screen of the API tokens
  follows is now written for every screen: in the answer to the `POST` that made it, with
  `Cache-Control: no-store` and a Copy button
  ([Design guide](developer/design-guide.md)).

- **Served under a path prefix.** An instance can live under a path, such as
  `https://example.com/housecairn/`, with `HOUSECAIRN_URL_PREFIX`: pages, static files,
  cookies, the installed application, the API and the links of emails, QR labels and
  calendar feeds follow it. A trusted proxy can also give the prefix of each request in a
  header named by `HOUSECAIRN_URL_PREFIX_HEADER`, as Home Assistant's Ingress does. See
  [Serving under a path prefix](administration/url-prefix.md).

- **Calendar and calendar feeds.** See your tasks by week, month or year, with filters by home,
  room, person and priority, **Done** and **Undo** in place, and the next dates of a task that
  repeats marked as forecast. **Calendar feeds** (**More**, **Calendar in another application**)
  gives a secret address per home, or for all your homes,
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
  cost, with what it comes to in a year when it repeats. Every page downloads as CSV, and
  the API has the same figures (read only), with your homes added up by currency, never
  converted. Amounts are typed the same way everywhere, with the comma in French: see
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

- **Seasons, display name, duration and contractors.** A task can be limited to a predefined season
  (spring, summer, autumn or winter) that follows the hemisphere of the home, which you set on the
  home page, or to custom months; existing windows become the matching season or a custom one. Each
  person can choose a display name on the new [profile](screens/profile.md) screen and in the API
  (`/api/v1/me/`), and the person in charge is shown by that name on every page, never by an
  address. The estimated duration is a number and a unit (minutes, hours, days, weeks, months or
  years). A task has a single contractor field, and each contractor has a
  [sheet](screens/contractor.md): trade from a list (plus Other), phone, email address, address,
  note and the tasks that name them, downloadable as a contact file (.vcf). Existing trades are
  matched to the list, otherwise kept under Other. See [Tasks and
  recurrence](guides/tasks-and-recurrence.md).

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

- **Amounts with the symbol of the currency.** Every amount now reads the same way on every
  screen, with the symbol of the currency when your language has one: `1 250,50 €` in
  French, `€1,250.50` in English, and the ISO code (`SEK`) when it has none. The cost of a
  task, its budgets and the last price paid to a supplier, which used to show the code
  next to the number, follow the same rule. Exports and the API are unchanged.

- **Back links on every screen.** The link at the top of a confirmation of the household
  names the screen it leads to instead of saying "Cancel", and the confirmation, the
  calendar feeds, a notification channel, the deletion of an account, the photo form, a
  sign-in provider, a section of the instance settings and a home that asks for a provider
  now lead back to the screen they were opened from, like every other screen. The calendar
  feeds lead back to More, where their entry is, instead of the calendar. About and
  **My homes**, renamed from "Homes" to match their entry of More, now have their link back
  to More on a phone. On a computer, the forms of a quote, a budget line, the annual
  envelope, a contractor, a supplier and a photo show their breadcrumbs.

- **A budget summary you read at a glance.** The top of the Budget page showed up to nine
  figures. It now shows three (what is set aside, **Spent** and **Left**) and a gauge with the
  share spent in words; a spending past the limit says **Over by ...** and *over budget*. The
  other figures (planned against the envelope, left to plan, paid, projects and upkeep apart,
  Budget in Sure) are under **Details of the year**. "Used, projects and upkeep" and "Left to
  spend" are gone: they were the same figures as **Spent** and **Left**.

- **The provider of a maintenance contract is preselected.** **Add a task** from an item
  whose maintenance contract names a provider now starts with that provider as the contractor
  of the task, when the home has a contractor of that name (whatever the case), and the
  **Who** section is open so that you see it. A provider that is not a contractor of the
  home is left alone: nothing is created until you save.

- **Design guide matches the code.** The [design guide](developer/design-guide.md)
  now lists the entries of More as they are, describes the back link of a form as it
  is drawn, and gathers the rules the code already follows: amounts through one filter,
  addresses built for a path prefix, links to typed addresses, and the first
  administrator screen reached from the sign-in page.

- **Tables that fit a phone.** The four views of Budget (summary, rooms, projects, upkeep),
  the budget of a room and the budget lines of a project no longer make the page scroll
  sideways: under 56 rem each row is a card, with the label of every value and the amount
  on the right. The comparison of projects keeps its columns in a scrolling area of its own.

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
- **Inspiration links.** The title field of the form to add a link has its own label and
  identifier: touching "Title" no longer puts the cursor in the field of the new task, and a
  screen reader names it. Adding a link while the preview is on is limited, per person (10 a
  minute) and per home (30 a minute), on the web and in the API (429), two new settings in
  the **Rate limits** section; a refused link is not added and no page is read. The guard of
  outgoing requests now also refuses the IPv6 site-local range `fec0::/10`. See
  [Projects](guides/projects.md) and [Rate limits](administration/rate-limits.md).

### Upgrade notes

- **The archive of a home changes format.** **Export all data** now gives format 2: a
  `manifest.json` with the digest of every file, one `data/<app>.json` per part of the
  application with every field of each table, and the files; its JSON Schema is published
  with the documentation. A script that read `export.json` must read the new documents.
  Archives of format 1 cannot be restored: export the homes again after the update
  ([Export and deletion](administration/data.md)).

- **The heating season becomes custom months.** It is no longer offered as a season: the
  update gives every task and project that had it a custom season of the same months
  (October to April in the north, April to October in the south), so nothing changes for
  them. An archive or a CSV file of before that holds `heating`, and an API client that
  still sends it, get the same months ([task form](screens/task-form.md)).

- **The paint left in stock and the unit of a stock item change shape.** The field
  `paint_stock` of a room is replaced by `paint_article` (a stock item of the home); the
  old text is kept, word for word, as a line `Paint left in stock: ...` of the memory
  notes, which can then exceed the 4,000 characters usual for notes until it is shortened.
  `unit` of a stock item now accepts the codes of the list (`piece`, `litre`, `metre`,
  `kilogram`, `roll`, `box`, `other`) with `unit_other`; usual spellings (pieces, litres,
  kg, rouleau) become the matching code, anything else is kept under Other. Both migrations
  are reversible: going back writes the text again (the plural of the list for a unit).
  Clients of the API must use the new names.

- **Photo categories and the contract of an item change shape.** The category `open_walls` of a
  photo is now `behind_walls`, in the API and in exports; the field `contract` of an item is now
  `contract_provider` (the old text, whole) and `contract_number`, in the API and in exports. The
  migrations are reversible, but going back turns the categories `before`, `after` and `other` into
  `general`, and joins the two fields of the contract into the one text again and cuts it at 200
  characters: the contract number is lost when the provider alone is longer than that. Clients of
  the API must use the new names.

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
