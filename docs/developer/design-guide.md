# Design guide

The rules every screen of HouseCairn follows: where it goes, how people come back
from it, how its actions behave and how it looks. They apply to every contributor,
human or agent, and the review of a pull request that adds or changes a screen
checks them with the [checklist](#new-screen-checklist) below.

The rules are normative. **Must** and **must not** are requirements; each comes with
its reason in one line. A screen that departs from them is a bug to fix, not a
precedent to follow.

Where the rules come from:

- the navigation decisions of the maintainer, recorded in
  [ADR 0053](../adr/0053-target-navigation-and-return-rule.md), and the visual
  system of [ADR 0017](../adr/0017-visual-system-and-brand.md);
- the navigation prototype validated by the maintainer on 2026-11-09,
  `design/navigation/prototype-navigation.html` in the repository: the reference for
  the **structure** of the screens (sections, tabs, return, actions in place);
- the v2 mock-up, `design/mockup/housecairn-maquette-v2.html`, and the design tokens,
  [`design/tokens.json`](../../design/tokens.json): the reference for the **look**;
- the navigation and design audits of the interface, summed up in the appendix
  [Why these rules](#why-these-rules).

The navigation described here is the target. It is built in several changes; until
they are all merged, some screens still differ from it. A change that alters one of
these behaviours updates the section of this guide that describes it, in the same
pull request.

## Information architecture

### Five sections

The application answers one question: what to do in the home, where, when, with what
and for how much. Each of the first four sections answers one part of it, and More
holds the rest.

| Section | Question | Tabs |
| --- | --- | --- |
| Today | What to do, and when | Today · All · Calendar |
| Rooms | Where, and with what | Rooms · Stock |
| Projects | Which works | In progress · Ideas · Finished |
| Budget | For how much | Summary · Rooms · Projects · Upkeep |
| More | Everything else | none: groups of links |

- The main navigation **must** have these five entries, in this order. Material 3
  and Apple's guidelines put three to five destinations in a bar; a sixth entry
  pushed Projects and Budget out of sight.
- A new entry **must not** be added to the bar without a new decision record. The
  bar is the map of the product; every entry added makes the others harder to find.
- A section **must** have four tabs at most, all visible at 360 px. A tab hidden by
  a horizontal scroll is a screen nobody finds.
- Tabs **must** switch between sister views of the same content, never lead to
  another section or a setting. Tabs used as a menu hide what they announce.
- A page **must** show one row of tabs at most. Two rows on a phone take half of the
  first screen.
- The history of the tasks is the **Done** filter of All, and each task shows its own
  history; it **must not** become a tab. A fourth tab of Today does not fit at 360 px.
- The calendar is a tab of Today, and the stock a tab of Rooms. The calendar is another
  view of the same occurrences; the stock is what is in the home, like the items.

### Phone: the bar at the bottom

Below 56 rem the sections are a bar fixed at the bottom of the screen. The app bar at
the top carries the logo, the current home (a selector from two homes on), search
and help.

```text
App bar: [logo] Current home ▾ (from 2 homes)                        [search] [?]
Bottom bar: Today · Rooms · Projects · Budget · More

Today                       tabs: Today | All | Calendar
├─ Today (root)             overdue, today, next 7 days; Report a problem; + Task
├─ All                      filters: room, person, state ("Done" is the history)
├─ Calendar                 Week | Month | Year (segmented control)
└─ Task ── Edit · Postpone · Details of completion · Files

Rooms                       tabs: Rooms | Stock
├─ Rooms (root) ── Room     Items · Tasks · Budget of the room · Photos · Memory
│                  └─ Item  Tasks of the item · Compatible stock · Report
└─ Stock ── Article         movements in place · Suppliers · Label

Projects                    tabs: In progress | Ideas | Finished
├─ Projects (root) ── Project   Quotes · Lines · Tasks · Links · Photos
│                               Compare (selection); Annual envelope → Budget
└─ Quote (form) · Line (form)

Budget                      tabs: Summary | Rooms | Projects | Upkeep
├─ Summary (root)           envelope of the year, variance, CSV export
├─ Rooms ── Room            budget detail, link "Open the room"
├─ Projects ── Project      link to the project
└─ Upkeep ── Task

More (root)
├─ Home: settings of the home · Household and roles · Reports (count)
│        · Contractors · QR labels · Export the data · My homes
├─ Me: Profile · Notifications · Display preferences · Calendar feeds
│      · Security and sign-in (deleting the account at the bottom)
├─ Instance (administrators only): Administration ── index ── one page per section
└─ Help: Help · API documentation · About                     [Sign out]
```

### Computer: the column on the left

From 56 rem the same `nav` becomes a column on the left. It lists the first four
sections, then the content of More unfolded under them, without a page in between,
and Sign out last.

```text
[logo]
Current home ▾
─────────────
Today
Rooms
Projects
Budget
─────────────
Home        Household and roles · Reports (2) · Contractors · QR labels · Settings
Me          Profile · Notifications · Security and sign-in
Administration (administrators only)
─────────────
Help · About · Sign out
```

The diagram is indicative and does not show every entry; the entries are those of
`housecairn/core/more.py`.

- The phone bar and the computer column **must** be one `nav`, laid out by CSS.
  Two navigations drift apart, and a screen reader would announce both.
- On a computer, More **must not** have its own page: its content is in the column.
  The width is there; a page in between costs a click for nothing.

### What goes in More

More holds four groups, in this order: **Home** (about the home being viewed),
**Me** (about the person), **Instance** (administrators only) and **Help**.

- An entry of More **must** belong to one of these groups. A flat list of eleven
  entries does not read at a glance.
- An action that cannot be taken back (deleting the account, a home) **must** be at
  the bottom of its own page, never on More. A dangerous action does not sit between
  two everyday settings.
- An entry of More **must** be added in `housecairn/core/more.py`, in its group, with
  its routes for the marking of the current entry, never in a template. The page of More
  and the column both show it.

### Where a new screen goes

Answer these questions in order, and stop at the first yes:

1. **Is it another view of the content of an existing section root** (a filter, a
   period, a grouping)? It is a tab of that section, if the section has fewer than
   four tabs; otherwise a filter of an existing tab.
2. **Is it the page of one record** (a room, an item, a task, a quote)? It goes under
   the page of its parent in the tree: an item under its room, a quote under its
   project.
3. **Is it the list of all the records of a new type of data across the home** (every
   warranty, every contract, every document of the home)? Choose the first place that
   fits, in this order:
   - *The page of a parent*, when each record belongs to one parent and is read from
     it (the warranty of an item, on the page of the item). A list that is only read
     from its parent needs no screen of its own.
   - *A tab of an existing section*, when the list is another view of what the section
     already shows, used often, and the section has fewer than four tabs. The stock is
     a tab of Rooms for this reason.
   - *More, group Home*, otherwise: the list is about the home but looked at now and
     then, not a daily view.

   A section never gets a fifth tab: that needs a new decision record
   ([ADR 0053](../adr/0053-target-navigation-and-return-rule.md)). A record that
   belongs to a parent record (the warranty of its item) keeps that parent in the tree.
   The cross-home list of More is only an origin, and returns to it with `next`. Only
   records with no other parent are pages under the list.
4. **Is it a form that adds or changes a record?** It is opened from the page or the
   list it belongs to, with a `next` address (see the [return rule](#return-rule)).
5. **Is it about the home but not daily use** (household, reports, labels,
   contractors, settings of the home)? More, group Home.
6. **Is it about the person** (profile, notifications, preferences, security)? More,
   group Me.
7. **Is it about the instance**? More, group Instance, shown to administrators only.
8. **Is it help or information about the application**? More, group Help.

A screen **must** be reachable from the navigation, never only from an address
typed by hand or a link in an email. A page nobody can reach again is lost after the
first visit.

## Return rule

> **People always come back to the screen they came from. When it is not known, to
> the parent in the tree. An action in place does not move them.**

### The `next` address

- A link that opens a record or a form from another screen **must** carry
  `next=<current path>`. Without it, the page cannot know where the person came from.
- `next` **must** be checked by `core.redirects.is_safe_redirect` before any use,
  through one shared helper, never by a check written again in a view. One rule
  for every page closes open redirects in one place.
- `next` **must** be a path relative to the application, cut to a reasonable length,
  and **must not** be nested: a `next` inside `next` is removed. An address that grows
  with every screen becomes unreadable and unsafe.
- `next` **must not** be shown as it is. The label of the back link comes from the
  route it resolves to. A parameter shown on screen can be forged by anyone who sends
  a link.
- A form **must** keep `next` in a hidden field, so that a form sent with an error
  still knows where to go back.

### In code

The rule has one implementation, `housecairn.core.navigation`, and its template tags,
`{% load navigation %}`. A view or a template **must** use them, never read `next`
itself.

| Helper | What it does |
| --- | --- |
| `back_url(request, default)` | The `next` of the request (the form first, then the query) when it is safe, else `default`. Safe: checked by `is_safe_redirect`, a path starting with one `/`, a nested `next` and `undo` removed, 512 characters at most (past that the query is dropped, then the address is refused). |
| `safe_next(request)` | The same, or `None` without a safe `next`. |
| `after_create(request, record_url, section_list, added=…, saved=…)` | Where a creation goes: `next`, with the message "*added* · Open" linking to `record_url`; the record itself when `next` is missing or is the route `section_list` (the list of its own section). |
| `after_delete(request, parent, gone)` | Where a deletion goes: `next`, unless its route names one of the ids in `gone` (the object and its children), else `parent`. |
| `label_for(url, request)` | The title of the screen a path leads to, from `LABELS`: a fixed label by route name, or a field of the record the route shows, read only in the homes the person may open. `None` for a route without a label. |

| Tag | Use |
| --- | --- |
| `{% back_link default %}`, `{% back_link default label %}` | The back link of the page. It leads to the safe `next` when its route has a label, named after it, else to `default`, named `label` or after the route of `default`. A link to More is shown on a phone only. |
| `{% back_href default %}`, `{% back_href default as cancel %}` | The same address without the link, for a Cancel button. |
| `{% url_with_next 'rooms:item-create' home_id=home.id room_id=room.id %}` | The address of a route with `next=<this page>`. A keyword prefixed with `q_` goes to the query: `q_item=item.id` gives `?item=…`. |
| `{% next_field %}` | The hidden `next` field of a form, with the safe `next` only. |

A form, then, reads:

```django
{% load i18n navigation %}
{% url 'rooms:detail' home_id=home.id room_id=room.id as parent %}{% back_link parent room.name %}
<form method="post">
  {% csrf_token %}
  {% next_field %}
  …
</form>
```

and its view ends with:

```python
return redirect(
    navigation.after_create(
        self.request, record_url, "rooms:list", added=_("Item added"), saved=_("Item added.")
    )
)
```

A route that should name a back link is added to `LABELS`. Without it, a `next`
to that route is not lost for the redirect after a form, but the back link falls back
to its default: a link must never show an address nor a nameless "Back".

### Default parent

A record reachable from two places has one parent in the tree, the section that owns
it, and the other place is only an origin.

- Without `next` (an address typed by hand, a link in an email or a calendar feed), the
  back link **must** lead to the parent in the tree, never to a previous screen
  guessed from the history. A page must not depend on a history the person cannot see.
- The parent **must** be the same wherever the record is opened from: the parent
  record when the record belongs to one (the warranty of its item), otherwise the list
  of its section, as in the tree above. The screen reference page
  of the record names it.
- With `next`, the origin wins and the label comes from its route.

Example: a room is listed under Rooms and also opened from the budget by room. Its
parent is Rooms, so opened without `next` it says "‹ Rooms". Opened from the budget
with `next`, it says "‹ Budget", keeps Budget marked in the bar and comes back to it.

### Back link and breadcrumbs

| Level | Phone | Computer (from 56 rem) |
| --- | --- | --- |
| Section root (Today, Rooms, Projects, Budget, More) | no back link | no breadcrumbs |
| Tab of a section (All, Stock, Ideas, budget by room) | no back link, the tab is marked | no breadcrumbs |
| Record (room, task, article, project) | `‹ <origin>` | `Section › … › Record` |
| Form | `‹ Cancel`, main action at the bottom | breadcrumbs, then Cancel and Save buttons |
| Page of More | `‹ More` (or the origin) | `Home › Household and roles` |

- A section root **must not** have a back link. A top-level destination has nowhere
  to go back to, and a back link there contradicts the bar.
- Every other page **must** have one, which names its target: never "‹ Back" alone.
  A person must know where the link leads before tapping it.
- The back link follows the origin; the breadcrumbs follow the tree.
- Breadcrumbs **must** appear on a computer only, as a `nav` with an `aria-label` and
  `aria-current="page"` on the last element. On a phone they take a line, and their
  targets would be too small.
- On a computer, the back link **must** appear only on a form or when the origin is
  not the parent (a room opened from the budget). Otherwise the breadcrumbs already
  say it.
- The entry of the bar that stays marked is the section the person entered by: a room
  opened from the budget keeps Budget marked, and comes back to it. The bar must never
  change tab under the finger.

### After a form

- **Created from a context** (a task from an item, an item from a room): the form
  **must** go back to `next`, with a message "Added · Open" whose link opens the new
  record. The person stays where they were working, and the record is one tap away.
- **Created from the list of its own section** (a project from the project list): the
  form **must** open the new record. The next step is there: adding a quote to a new
  project.
- **Cancel** **must** lead to `next` as well, or to the parent without it.
- **Changed** (edit form): back to `next`, or to the record without it.

### After a deletion

- A deletion **must** go through a confirmation page: a link to the page, then a post
  from it, whose Cancel link goes back to the object. This includes photos, files and
  the revocation of a label. A tap by mistake must not lose a document.
- After the deletion, the person **must** land on the parent of the deleted object,
  never on `next` if it points to that object or one of its children. That page no
  longer exists.

### The bar, and the browser's back button

- Tapping a section in the bar or the column **must** lead to its root. Tapping the
  section already marked **must** go back to its root and to the top of the page. Both
  are what iOS and Android do, so people expect them.
- The browser's back button, or the system one in the installed application, **must**
  give the same result as the back link. In the installed application on iOS there is
  no system back button: the back link is then the only way back.
- A creation form **must** be sent with `Cache-Control: no-store` and a one-time
  token against a second sending. Going back to a sent form must not create a
  duplicate.
- A transient state (an undo banner, a message) **must not** live in the address.
  Going back would show it again, out of date.

## Actions in place

An action that takes one tap and can be undone **must** keep the person where they are:
Done, Skip, Undo, postponing by one day, a stock movement, the status of a quote.

- With JavaScript, the form **must** post with HTMX (`hx-post`) and replace only the
  fragment concerned (the row of the occurrence). The address does not change. Done is
  the most frequent gesture; a reload sends the page back to its top, and the person
  loses their place.
- The confirmation **must** be an undo banner at the bottom of the screen, above the
  bar, in an `aria-live="polite"` region, visible for at least 8 seconds, with an
  Undo button. Near the finger, announced by screen readers, and long enough to read.
- The banner and the bar **must not** hide the focused element (WCAG 2.2, 2.4.11).
- Without JavaScript, the same form **must** still work: a post, then a redirect to
  `next#<anchor>` (for an occurrence, `#occ-<id>`), which brings the person back to
  the row. After an undo, the redirect drops the undo state from the address.
- Done **must not** ask for a confirmation: Undo is the safety net
  ([ADR 0033](../adr/0033-done-with-undo.md)). A question on every task is the
  friction that makes people stop using the application.

An action **must** open a screen instead when:

- it needs more than one tap of input: the details of a completion (date, cost,
  note), postponing to a chosen date, a quantity other than the one offered;
- it cannot be taken back: a deletion goes through its confirmation page;
- it changes who may do what: roles, transfer of a home, an invitation sent by email.

## Current home

Most households have one home; some have two or more (a second home, a rented
flat).

- The current home **must** be remembered for the session. Every section then opens
  on it, without a page that asks which home at each change of section.
- The selector of the current home **must** appear in the app bar only from two homes
  on. A selector with one choice is noise.
- Today **must** offer "All homes" in the selector; the other sections show one home
  at a time.
- A page of a home **must** keep the home in its address
  ([ADR 0010](../adr/0010-stable-urls.md)). The current home only chooses where a
  section root opens; a link to a page always opens the same page.

**Isolation.** Every query **must** be scoped to the homes of the person
([ADR 0006](../adr/0006-home-scoping.md)), and the current home **must not** replace
that check. A value kept in a session is a preference, not a permission. The
selector and "All homes" list only the homes the person belongs to, and a home they
left is dropped from the session.

## Dates, reminders and alerts

The application already has one way to remind and one way to alert; a new screen uses
them and does not add a third.

- A date that someone must act on **must** be a task with a due date. The task is then
  shown on Today: overdue, today, and up to the person's horizon, 7 days by default
  (the `horizon_days` preference, `Horizon.WEEK`). It is also shown on the Calendar and
  in the calendar feeds, and its reminders go out through the channels of the person
  ([ADR 0043](../adr/0043-notifications-through-apprise.md)), with the rules of
  postponing, Done and Skip that every task has. A reminder written again for one
  screen would ignore the quiet hours and the follow-ups of the person.
- A date that only informs (the end of a warranty) **must** be a list of the agenda
  digest, `housecairn.tasks.agenda.my_home`, shown on My home (`/me/`, the view of Today
  when the person is not in a home), as the warranties ending soon are today.
  It is read, not acted on, and sends no notification. This digest is not the daily
  summary message of the notifications.
- An event with no due date (a problem was reported) **must** be an alert of
  `housecairn.notifications.alerts`, sent in the background to the members who may
  write, except the person who caused it, with the quiet hours applied. The open
  reports are also a line on Today with a link, for the members who may write.
- A notification **must** carry the title the person typed, the home and a link, and
  nothing else: no amount, note or address leaves the instance.
- A notification **must not** be sent from the screen's own code: it goes through the
  `notifications` app, which sends it once and only to people who have a channel on.

## Screen rules already decided

These rules come from earlier decisions; this guide gathers them so that a new screen
is checked against all of them at once.

- **Amounts** **must** be shown in the format of the language of the reader, with the
  symbol of the currency: `1 250,50 €` in French. Every amount goes through the same
  template filter. Three formats on three screens read as three different numbers.
- **Deleting** **must** go through a confirmation page (see
  [After a deletion](#after-a-deletion)). Only Done and its siblings rely on Undo.
- **Lists**: wherever a generic list exists (type of room, category of a photo, trade
  of a contractor), the field **must** offer it, with "Other" as its last choice
  ([ADR 0045](../adr/0045-generic-lists-with-other-tabs-and-audit-of-content.md)).
  Free text makes filters impossible and translations arbitrary.
- **People** **must** be shown by their display name (`accounts.names.person_name`),
  never by their email address, except on a page whose subject is the address (the
  card of a household member, a contractor). An address on every screen is personal
  data shown to the whole household.
- **Sign-in** **must** offer one button per configured identity provider, and passkeys
  through the browser's autofill of the address field, without a passkey button
  ([ADR 0018](../adr/0018-sign-in-page-and-passkeys.md)). The page stays a form and at
  most one button per provider.
- **Touch targets** **must** be at least 44 px (`--hc-layout-touch-target`), and the
  Done button 48 px (`--hc-layout-touch-target-lg`). A small link in a table is missed
  by a finger.
- **Focus** **must** always be visible: the focus ring of the tokens, never an
  `outline: none` without a replacement. A keyboard user who cannot see the focus
  cannot use the page.
- **Accessibility**: every screen **must** meet WCAG 2.2 level AA. It is the level the
  project commits to for every screen, not only for the sign-in pages.
- **Widths**: every screen **must** be tried at 375 px and at 1280 px: no horizontal
  scroll of the page (a wide table scrolls in its own container), every tab visible.
  The application is designed for the phone first; the computer layout must not
  break either.
- **Language**: every string **must** go through the translation functions, with
  English as the source ([ADR 0013](../adr/0013-internationalization.md)). The French
  text **must** be written with care: the formal *vous*, agreement with the noun it
  qualifies, and a `pgettext` context when one English word needs two French words.
  French ships with the first version, and a mistake in a list is seen on every visit.
- **Resources**: a screen **must not** load anything from another host, nor use an
  inline style or script ([ADR 0011](../adr/0011-no-external-resources-and-csp.md)).
  The strict content security policy refuses them.

## Visual system

The visual system was laid down with the application shell in J1-F
([ADR 0017](../adr/0017-visual-system-and-brand.md)). The values are in
[`design/tokens.json`](../../design/tokens.json) and nowhere else: this guide does not
repeat them.

- A colour, size, spacing, radius or shadow **must** come from a `--hc-*` variable,
  never from a value written in a CSS file. A value written twice drifts.
- A change of value **must** be made in `design/tokens.json`, then
  `manage.py build_design_tokens`, and the generated `tokens.css` committed. The
  contrast test then fails if the change breaks AA.
- A screen **must** use the components of `static/css/components.css` before creating
  one: cards, lists and rows, buttons (primary, secondary, sand, danger, icon), fields,
  pills, alerts and messages, the segmented control, chips and the tab bar
  (`{% tab_bar %}`). A component made twice looks different twice.
- A new component **must** go in `components.css`, built on the tokens, and be usable
  by every screen. A style local to one page becomes the next inconsistency.
- The danger button **must** be kept for the action that destroys, on its confirmation
  page. Red everywhere means nothing.
- Icons **must** come from `templates/components/icon.html`, as inline SVG. One set,
  one look, nothing loaded from elsewhere.
- The v2 mock-up is the visual reference of every screen; a deviation **must** be
  recorded in a decision record with its reason, as ADR 0017 does for contrast. The
  navigation prototype is a reference for structure only: its look does not count.

## New screen checklist

Copy this list into the pull request that adds or changes a screen, and tick what
holds. The review checks the same list.

- [ ] The screen has its place in the tree, found with
  [Where a new screen goes](#where-a-new-screen-goes), and is reachable from the
  navigation.
- [ ] A new entry of More is added in `housecairn/core/more.py`, in its group, with its
  routes for the marking, and in no template.
- [ ] A record reachable from two places has one parent, named in its screen reference
  page; without `next`, its back link leads to it.
- [ ] A date to act on is a task; a date that informs is a list of the agenda digest; an event
  is an alert; none has a reminder of its own.
- [ ] The bar still has five entries; the section has four tabs at most, all visible
  at 360 px, and the page shows one row of tabs at most.
- [ ] The marked entry of the bar is the section the person entered by.
- [ ] A section root has no back link; any other page has one that names its target.
- [ ] Every link to a record or a form carries `next` (`{% url_with_next %}`), the
  back link and Cancel use `{% back_link %}` and `{% back_href %}`, and the form keeps
  `next` with `{% next_field %}`; a route that a back link must name is in `LABELS`.
- [ ] After a creation from a context, the person is back in the context with
  "Added · Open"; from the list of its own section, on the new record.
- [ ] A deletion goes through a confirmation page and lands on the parent.
- [ ] Each new named web route has its entry in `housecairn/parity.py` (the API route
  that does the same, or an exemption with its reason), and its API endpoint, as
  [ADR 0003](../adr/0003-web-api-parity.md) requires; `tests/test_parity.py` passes.
- [ ] Tests of the return rule, as [ADR 0053](../adr/0053-target-navigation-and-return-rule.md)
  announces: for each new link that carries `next` and each new form, the origin, the
  label of the back link and the target after sending, with and without `next`. They
  fail on the code without the change.
- [ ] One-tap actions stay in place with HTMX, with the undo banner, and work without
  JavaScript.
- [ ] The screen shows the current home and only data of the person's homes.
- [ ] Amounts in the format of the language with the currency symbol; people by their
  display name; generic lists with "Other".
- [ ] Touch targets of 44 px at least, visible focus, never hidden by the bar or the
  banner; WCAG 2.2 AA.
- [ ] Tried at 375 px and 1280 px, with no horizontal scroll of the page.
- [ ] Every string translated, the French text reread.
- [ ] Only `--hc-*` tokens and existing components; no inline style or script, nothing
  from another host.
- [ ] The screen reference page in `docs/screens/` and this guide, if a rule changed,
  updated in the same pull request.

## References

- Material Design 3:
  [navigation bar](https://m3.material.io/components/navigation-bar/guidelines),
  [navigation drawer](https://m3.material.io/components/navigation-drawer/guidelines),
  [tabs](https://m3.material.io/components/tabs/guidelines),
  [snackbar](https://m3.material.io/components/snackbar/guidelines).
- Android, [principles of navigation](https://developer.android.com/guide/navigation/principles)
  (a fixed start destination, Up and Back).
- Apple Human Interface Guidelines:
  [tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars),
  [navigation bars](https://developer.apple.com/design/human-interface-guidelines/navigation-bars).
- Nielsen Norman Group:
  [10 usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/),
  [breadcrumbs](https://www.nngroup.com/articles/breadcrumbs/),
  [tabs, used right](https://www.nngroup.com/articles/tabs-used-right/).
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/), in particular
  [2.5.8 Target size (minimum)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html),
  [2.4.7 Focus visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html),
  [2.4.11 Focus not obscured (minimum)](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html),
  [2.4.6 Headings and labels](https://www.w3.org/WAI/WCAG22/Understanding/headings-and-labels.html),
  [3.2.3 Consistent navigation](https://www.w3.org/WAI/WCAG22/Understanding/consistent-navigation.html),
  [3.2.6 Consistent help](https://www.w3.org/WAI/WCAG22/Understanding/consistent-help.html)
  and [4.1.3 Status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).
- web.dev, [app design](https://web.dev/learn/pwa/app-design): in the installed
  application, the browser shows no navigation of its own.

## Why these rules

A navigation audit of the interface, on 2026-11-09, walked through the main journeys
at 375 px and 1280 px in French, with three roles (owner, member, read-only). It found
16 problems: 2 blocking, 9 important, 5 minor. The interface itself was sound (touch
targets, skip link, consistent help, confirmation before deleting most objects, a
`next` already checked); the problems were structural. A design audit a few days
earlier had found the same first problem (Projects and Budget out of sight on a
phone), and the rules on amounts, deletions and lists.

| Finding | Severity | What the audit saw | Rule that answers it |
| --- | --- | --- | --- |
| NAV-01 | blocking | Six entries in the bar; Projects and Budget were tabs of Tasks, off screen at 375 px. | [Five sections](#five-sections) |
| NAV-02 | blocking | Every back link pointed to a fixed parent, every form to the new record: a task added from an item left the person three taps from the item. | [Return rule](#return-rule) |
| NAV-03 | important | Three contradictory signs of position on one screen: the back link, the marked entry, the title. | [Back link and breadcrumbs](#back-link-and-breadcrumbs) |
| NAV-04 | important | Three home screens; the installed application opened on the least useful. | Today is the start screen ([ADR 0053](../adr/0053-target-navigation-and-return-rule.md)) |
| NAV-05 | important | Done reloaded the page and sent it back to the top; the undo banner was far from the finger. | [Actions in place](#actions-in-place) |
| NAV-06 | important | Eight tabs of Tasks mixing views, other sections and a setting. | [Five sections](#five-sections) |
| NAV-07 | important | Six taps for a read-only person to report a problem. | Report a problem on Today, reports in More |
| NAV-08 | important | With two homes, every section asked again which home. | [Current home](#current-home) |
| NAV-09 | important | More was a flat list of eleven entries, deleting the account among them. | [What goes in More](#what-goes-in-more) |
| NAV-10 | important | Instance settings on one page of almost ten screens, with nine identical Save buttons. | One index, one page per section |
| NAV-11 | important | The page of a room did not lead to its budget. | Budget of the room on its page |
| NAV-12 | minor | The browser's back button showed out-of-date undo banners and reopened sent forms. | [The bar, and the browser's back button](#the-bar-and-the-browsers-back-button) |
| NAV-13 | minor | No breadcrumbs on a computer. | [Back link and breadcrumbs](#back-link-and-breadcrumbs) |
| NAV-14 | minor | Ambiguous or duplicate labels ("Home" opening "My home", one object with two names). | One term per concept; bar labels equal the titles of their roots |
| NAV-15 | minor | Repetition folded away when adding a task from an item, whose tasks all repeat. | Repetition open by default for a task of an item |
| NAV-16 | minor | The calendar outside the home, with no back link. | The calendar is a tab of Today |

The audit compared the interface with Material 3, Apple's guidelines, the Nielsen
heuristics and WCAG 2.2 (see [References](#references)), and with other home
management applications. The full report stays outside the repository; this table
and [ADR 0053](../adr/0053-target-navigation-and-return-rule.md) keep what was
decided from it.
