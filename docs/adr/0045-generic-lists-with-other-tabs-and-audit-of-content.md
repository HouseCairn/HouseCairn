# 0045. Generic lists with "Other", tabs, language of a person and audit of content

- Status: accepted
- Date: 2026-11-08

## Context

The first tests of the application showed fields that ask people to type what a short,
world-wide list would say better: the kind of photo, the type of a room, who services an
item and under which contract number. Free text there makes filters impossible and
translations arbitrary. The maintainer's rule: wherever a generic list exists, offer it.

## Decision

**A generic list is a closed list of codes, translated, plus "Other".** The field stores
the code (`behind_walls`), never the label; the label is a `gettext` string of the
language of the reader, so a list is translated once for everyone. "Other" is always the
last choice and never hides information: what "Other" means is said in a field that already
exists (the name of a room, the caption of a photo) or, when none does, in a free-text field
next to the code (the trade of a contractor, in the lot that follows).

- **Photo categories**: `general`, `behind_walls`, `before`, `after`, `other`. One list for
  all the photos of a room or an item; the room page filters it by category (`?category=`),
  the API already does. `behind_walls` carries a help line (pipes and cables before the wall
  is closed, to know where not to drill). The earlier `open_walls` becomes `behind_walls`;
  the data migration is reversible: going back, `behind_walls` returns to `open_walls` and
  the categories that did not exist before return to `general`, so no photo is lost.
- **Room type**: the existing list, now the first field of the form. Choosing a type fills in
  the name with its label, which stays editable; a script of the instance
  (`static/js/room-form.js`, no library) does it as the type is chosen, and the form does the
  same on the server when the name is left empty, so the screen works without script. With
  "Other" there is no label to offer and the name is required. The type serves the icon, the
  filters and, later, the task templates of a room.
- **Maintenance contract of an item**: two fields, the provider and the number. The old text
  (who services it, and the number if any) goes whole into the provider; going back, the two
  are joined by " · ".
- **Brand of an item**: free text with suggestions. The brands already entered in the home,
  once each whatever the case, are offered in a `datalist` of the form; it is a suggestion
  and not a list: any other brand is kept. The suggestions are those of the home only.

**Sub-navigation.** The links between the screens of one area (Today, All tasks, History and
Display preferences; Overview, Household and roles and Audit log of a home; the pages of the
instance administration) are one component, `{% tab_bar %}` (`core/templatetags/tabs.py`,
`components/tabs.html`), built on the `--hc-*` tokens: a `nav` with a list of links, the
current tab marked by `aria-current="page"`, a horizontal scroll when the tabs do not fit, a
touch target of `--hc-layout-touch-target` and the focus ring of the interface. A tab is shown
only to the people who may open it: the audit log of a home to its owners. The display
preferences page belongs to no home; it shows the tabs of the home named by its `next`
address only if that is a page of a home the person may open.

**Language of a person.** A `language` on the display preferences (empty: automatic) wins
over the cookie, the browser and the default of the instance (ADR 0042). A middleware after
authentication activates it, so it applies from the next page; a request authenticated by an
API token only is not known to it and keeps the language it asks for.

**Audit of content.** Rooms, items, tasks, photos and the files of a task are recorded when
added, changed or deleted, by `audit.record_object`: the title of the object as a person
named it (a photo or a file: the room, the item or the task it belongs to), cut to 120
characters and on one line, and for a change the names of the fields that changed, never
their values. No note, cost, procedure, file name or file. The entries stay in the home's log
(owners only) and go with the home.

## Consequences

- API clients that wrote `open_walls` or the `contract` field must use the new names; exports
  carry them too.
- A list is not extensible by the household: a missing value is "Other" plus text. A list that
  grows is a change of the code, translated for all.
- The contractor record (a trade list, a phone, an e-mail and an address, a vCard download),
  the seasons of a task and the display of the person in charge by name follow in a separate
  lot; this decision is completed there.
