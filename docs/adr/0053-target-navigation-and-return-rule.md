# 0053. Target navigation and return rule

- Status: accepted
- Date: 2026-11-09
- Extends: [0017](0017-visual-system-and-brand.md) (application shell),
  [0033](0033-done-with-undo.md) (Done with undo)

## Context

The application grew one screen at a time, and its navigation with it. A navigation
audit of `main` on 2026-11-09 (16 findings, NAV-01 to NAV-16, summed up in the
[design guide](../developer/design-guide.md#why-these-rules)) found a structure that
was not the one decided: six entries in the bar, Projects and Budget hidden as tabs
of Tasks, three home screens, back links that pointed to a fixed parent whatever the
origin, and Done reloading the page to its top. The interface itself was sound; the
problems were structural, and every business screen still to come would have
repeated them.

The audit proposed a target tree, a single return rule and six questions. The
maintainer answered them and validated the target and its prototype on 2026-11-09.
The shell clause of [0017](0017-visual-system-and-brand.md) is amended on its own for
the bar, the tabs and More; this record holds the whole target, the return rule and
the reasons for each choice.

## Decision

**Five sections.** On a phone, the bar at the bottom is Today, Rooms, Projects,
Budget and More. From 56 rem the same navigation is a column on the left that lists
the first four sections, then unfolds the content of More, without a page in between.
Today is the start screen: the address of the installed application, the redirect
after signing in and the logo all lead to it. Each section has four tabs at most,
sister views of the same content, all visible at 360 px. More is in four groups: Home,
Me, Instance (administrators only) and Help.

**Q1, the stock** is a tab of Rooms: Rooms | Stock.

**Q2, a creation started from a context** (a task from an item, an item from a room)
goes back to the context, with a message "Added · Open" whose link opens the new
record. One exception: when the origin is the list of the section itself, the new
record opens, because the next step is there.

**Q3, the bar**: tapping a section always leads to its root. Tapping the section
already marked goes back to its root and to the top of the page.

**Q4, several homes**: the current home is remembered, with a selector in the app
bar that appears only from two homes on. Today offers "All homes". The current home
is a preference, never a permission: every query stays scoped to the homes of the
person ([0006](0006-home-scoping.md)).

**Q5, the history** of the tasks is a "Done" filter of the list of all tasks, and
each task shows its own history. There is no history tab.

**Q6, Done, Skip and Undo** work without reloading the page. HTMX replaces the row
alone, an undo banner appears at the bottom, and without JavaScript the same form
redirects to `next#<anchor>`. Undo itself stays the service of
[0033](0033-done-with-undo.md); only the way the web answers changes.

**Return rule.** People come back to the screen they came from; when it is not known,
to the parent in the tree; an action in place does not move them. The origin travels
in a `next` parameter, which is:

- always checked by `core.redirects.is_safe_redirect`;
- a path relative to the application;
- cut to a fixed length;
- never nested: a `next` inside `next` is removed;
- never shown as it is: the label of the back link comes from the resolved route.

A section root has no back link; every other page has one that names its target. On
a computer, breadcrumbs follow the tree, and the back link appears only on a form or
when the origin is not the parent. The section marked in the bar is the one the
person entered by. After a deletion, confirmed on its own page, the person lands on
the parent of the deleted object. The browser's back button gives the same result as
the back link: creation forms are not cached and carry a one-time token, and no
transient state lives in the address.

**Unchanged.** Amounts in the format of the language with the currency symbol
(`1 250,50 €` in French), a confirmation page before any deletion, generic lists with
"Other", people shown by their display name and never by their email address, the
visual system of [0017](0017-visual-system-and-brand.md) with `design/tokens.json`,
and no screenshots in the documentation or the CI.

**Where the rules live.** The design guide, `docs/developer/design-guide.md`, states
them as rules for every new screen, with a checklist for review. The prototype,
`design/navigation/prototype-navigation.html`, is the reference for the structure;
the tokens and the v2 mock-up remain the reference for the look.

## Options considered

- **Bar.** Keeping the six entries (Home, Homes, Rooms, Tasks, Stock, More) was
  rejected: Projects and Budget, two of the four questions of the product, stayed
  hidden, and Homes, rarely used, kept a place.
- **Q1.** The stock as an entry of More was rejected: restocking would be two taps
  further, and the stock is what is in the home, like the items, whose page already
  lists their compatible stock. As a tab of Today it was rejected too: tabs are views
  of the same content, and the stock is not a view of the tasks.
- **Q2.** Opening the new record, whose back link would lead to the context, was
  rejected: the person would land one screen away from where they were working, for
  a record the message already opens in one tap.
- **Q3.** Showing the last screen visited in the section was rejected: what a tap
  shows would depend on a history the person cannot see, and the return rule already
  brings people back to where they came from.
- **Q4.** Choosing the home at each entry, the former behaviour, was rejected: it adds
  a screen at every change of section for any household with two homes. "All homes"
  everywhere, with a filter, was rejected: most households have one home, and adding a
  room or a task needs one home anyway.
- **Q5.** A fourth tab of Today was rejected: it does not fit at 360 px next to Today
  and Calendar, and the history is the "Done" state of the same list.
- **Q6.** Keeping the reload, with an anchor to the row, was rejected as the main path:
  the page still reloads and the undo banner stays far from the finger. It remains the
  fallback without JavaScript.

## Consequences

- The target is built in several changes, each of which updates the section of the
  design guide it concerns. Until they are all merged, some screens differ from it;
  the guide, not the screen, says what is right.
- Every link to a record or a form carries `next`, and every view that reads it goes
  through one shared helper; the tests of the return rule follow the measured journeys
  (origin, back link, target after sending).
- A new section, or a fifth tab in a section, needs a new record. A screen that does
  not fit the tree is the sign that the tree must change first.
- A change of the navigation updates the prototype in the same pull request
  (`design/navigation/README.md`), so that it stays the reference.
