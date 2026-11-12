# 0063. A search field with chips for multiple choices among the records of a home

- Status: accepted
- Date: 2026-11-12
- Extends: [0011](0011-no-external-resources-and-csp.md) (no inline script), [0013](0013-internationalization.md) (every string translated)

## Context

Two forms asked for several records of the home with a list of boxes: the equipment a stock item
fits and the rooms where it is used, and the rooms of a project. Such a list grows with the home:
fifty items in a column of boxes is a long scroll on a phone, and finding one means reading all of
them. The maintainer decided on 2026-11-11 that a multiple choice among the records of a home is a
search field that holds one removable chip per choice, with the boxes kept only for a short, fixed
list.

## Decision

- **One component.** `core.widgets.ChipSelectMultiple` is a Django widget that renders the native
  `<select multiple>` (`templates/components/chip_select.html`), and `static/js/chip-select.js`
  turns it into a search field, a list of suggestions and the chips. The native select stays in the
  page, hidden by the script, and is what the form submits: the values posted are those a select
  posts, so the fields, the forms, the services and the API do not change, and a value that is not
  a choice of the queryset (a record of another home) is refused as before.
- **Without script, the select shows.** Its options are grouped when the field names a group
  (`group_by`): the items of the stock form are grouped by room. A grouped list is the filter of the
  page without script; the form is submitted as it is. No server-side filter is added: a field that
  needs one is the field to give a search route to, below.
- **Suggestions are filtered in the browser**, over the options already in the page. The lists
  concerned are the rooms and the items of one home, a few hundred entries at the most, a few
  kilobytes in the page. A route of search (HTMX) would be a new address to guard (membership of the
  home, role, parity with the API), a round trip at each key and a state to keep when the form is
  refused. It is the answer when a list reaches several thousand entries; none does now, and the
  widget is the one place to change then. The list shows 50 suggestions at most and says how many
  there are.
- **The pattern is the combobox with a listbox popup** of the ARIA Authoring Practices. The search
  field has the role `combobox` and the `id` of the field, so its label and the link of the summary
  of errors reach it; the list is a `listbox` of `option`s, the highlighted one named by
  `aria-activedescendant`; a polite live region announces the number of results, a choice added and
  a choice removed. Keys: the arrows open the list and move in it, Enter picks the highlighted
  suggestion (or the first match of what was typed, and never submits the form while something is
  typed), Escape closes the list, Backspace in the empty field removes the last chip. A chip is a
  button named "Remove <name>", reachable with Shift+Tab and pressed with Enter or Space.
- **Touch and sight.** Chips, their buttons and suggestions are 44 px high at least; the field draws
  its focus ring around the whole box; the highlighted suggestion has a bar as well as a colour;
  nothing scrolls sideways at 375 px. A name that has a group shows it ("Kitchen · Oven").
- **People** are shown by their display name wherever the component lists some (the label of the
  option is the one of the field); no field of this kind lists people today.
- **What stays boxes.** A short, fixed list: the permissions of an API token, the equipment ticked
  when a home is created, the homes of an API token (a few, some disabled with the reason), and the
  options on or off. Two screens select rows of a list to act on them (the QR labels to print, the
  projects to compare); the row carries information and a link, so they stay lists of rows with a
  box each.

## Consequences

- A new multiple choice among records uses the widget and loads the script
  (`{% block extra_head %}`), as the two forms do; the design guide says so.
- Nothing is submitted by the script: with a script that fails to load, the page is the page
  without script.
- The browser check (`tests/e2e/chip_select_checks.py`) drives the keyboard, the chips and the form
  at 375 and 1280 px and without script. axe-core is not a dependency of the project, so the
  references its rules would check are asserted there instead.
