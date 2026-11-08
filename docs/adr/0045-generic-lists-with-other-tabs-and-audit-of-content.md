# 0045. Generic lists with "Other", tabs, language of a person, seasons, contractors and audit of content

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
(owners only) and go with the home. The log names people as every other page does, through
`person_name`: on the screens the name, never the address; in the API `actor_name` and
`target_name` (empty for a deleted account or the system) next to the `actor_email` and
`target_email` that existed.

**Seasons and the hemisphere of the home.** A task limited to a season takes a `season`:
`spring`, `summer`, `autumn`, `winter`, `heating` or `custom`, empty for the whole year. The
predefined ones are whole months: spring March to May, summer June to August, autumn
September to November, winter December to February, the heating season October to April, in
the northern hemisphere, and the same shifted by six months in the southern one. The
hemisphere is a field of the home (`north` by default, set on the home screen and by the
API), never guessed from a place or a language, since a household decides it once and a
guess would be wrong for part of the world. The months stay on the task
(`season_start_month`, `season_end_month`) and always hold the window, so the recurrence
engine and the Today query are unchanged: a predefined season writes the window of the
hemisphere of the home when the task is saved, and changing the hemisphere rewrites the
tasks of that home that use a predefined season (`resync_seasons`); a custom season keeps
the months the person chose. Months sent without a season (a client older than this
decision) make a custom one. The data migration is reversible: a window that is exactly a
northern predefined season becomes it and any other window becomes a custom season; going
back drops the `season`, and the months, which never left, are the window.

**Display name.** The account has an optional `display_name` (60 characters, one line, no
control or invisible character), edited on the profile screen and by `PATCH /api/v1/me/`.
One helper, `accounts.names.person_name`, names a person everywhere: the display name, then
the full name, then the part of the address before the `@`. A person is never shown by their
whole address except where the address is the subject (their account, an invitation, the
sheet of a member). The administration site still shows the display name read only and
cannot take an account over (ADR 0022).

**Routes under `me/` and API tokens.** What belongs to the person, and not to a home, is
not an API token's to change: a token is tied to some homes and stands for an integration.
It may read where it could (the `GET` routes keep the rules they had), and every method
that changes something is for the person signed in, as the erasure of the account is
(`SignedInPerson`, shared by the views as the `PersonOnlyToChange` mixin; a token gets a
403 and nothing is created, changed or sent). The name shows in every home of the person,
which is wider than the homes a token is tied to; a channel makes the server send
messages; the display preferences are the person's own layout.

| Route | Methods | API token |
| --- | --- | --- |
| `me/` | `GET`, `PATCH` | reads; `PATCH` refused |
| `me/home/` | `GET` | reads |
| `me/display-preferences/` | `GET`, `PATCH` | reads; `PATCH` refused |
| `me/notification-channels/`, `.../<id>/` | `GET`, `POST`, `PATCH`, `DELETE` | reads (with the `write` scope); `POST`, `PATCH`, `DELETE` refused |
| `me/notification-channels/<id>/test/` | `POST` | refused (it sends a message) |
| `me/notification-preferences/` | `GET`, `PATCH` | reads (with the `write` scope); `PATCH` refused |
| `me/notifications-export/` | `GET` | reads (with the `write` scope) |
| `account/delete/` | `POST` | refused |

A display name is refused when it contains an `@` (in any width: the full-width form counts),
which would pass for an address, or when nothing in it draws (spaces, the Hangul fillers
U+115F, U+1160, U+3164 and U+FFA0, the blank Braille pattern U+2800, bare combining marks). Those fillers,
the Khmer inherent vowels U+17B4 and U+17B5, the combining grapheme joiner U+034F and
spaces of any kind (U+3000, U+00A0...) are removed at either end of a name that has
something else (`Sam` followed by U+3164 is `Sam`); inside a name they stay, so a Persian
word with its zero-width non-joiner and a composed emoji with its joiners are kept as typed. Emptying it stays possible. In a list where one
picks a person (the assignee of a task, the "Done by" filter of the history) and in the
audit logs of a home and of the instance, two members of the same name show their address
in brackets after it; a name that is alone shows no address.

**Comparing names.** The rule is a principle, not a list: two names are the same when they
look the same on screen, and what does not change the display does not count. The key
(`accounts.names.same_name_key`) decomposes the name (NFKD, so that full-width letters and
ligatures become plain ones), folds the case, drops every character of the Unicode categories
Cc, Cf, Mn and Me and the blank glyphs (the Hangul fillers, U+2800, U+17B4, U+17B5, U+034F,
U+180E), and reads any run of spaces as one. The decomposition comes before the removal so
that a mark inserted after a letter cannot fuse with it into a letter that stays; the price
is that accents do not count either (`José` and `Jose` get their address shown), which costs
an address shown more often and never less. A property test inserts any such characters
anywhere in a name and checks that the key does not move.

**What is not compared: look-alikes of another alphabet.** A Cyrillic `Ѕаm` is a different
name from `Sam` for this rule, as is any letter that merely resembles another. Telling them
apart needs a confusables table that keeps growing, and a rule by list is a race against
the next character. The name is a courtesy, not an identity: the address in brackets when
two names coincide, and the role, are the only proof of who a person is, and nothing in the
application relies on a display name for access.

**Estimated duration.** A number and a unit (minutes, hours, days) on the screens, minutes
in the data and in the API, between one minute and thirty days; the service layer checks the
bounds for every way in. The page shows it as people say it ("45 min", "1 h 30", "2 days"),
and the form shows a stored value back in the biggest unit that holds it exactly. The bound
is held when the duration is set or changed, not each time the task is saved: a task kept
from before it (a duration of 0 was accepted) can be renamed or moved. The migration
`0007_estimate_zero_unset` turns such a 0 into "no estimate"; undone, it leaves them unset.

**Contractors.** A contractor belongs to one home and has a name (the only required field),
a trade, a phone number, an email address, an address and a note. The trade is a code of a
generic list (plumber, electrician, heating engineer, roofer, carpenter, painter, mason,
gardener, locksmith, chimney sweep) or `other`, which requires `trade_other`, the trade in
the person's own words; the text is dropped when a listed trade is chosen. The data
migration is reversible: a trade written as free text becomes the code of the list when it
is the same word in English or in French, whatever the case and the accents, and otherwise
becomes `other` with the text kept; going back writes the English label, or the text kept.
The task has one field for the contractor: the name is typed or picked from a `datalist` of
the home (a browser feature, no script, which is a plain text field where it is not
supported); a name the home already has, whatever its case, picks that contractor and a new
one creates it when the task is saved, in the same transaction: a form that is refused
leaves no contractor and no audit line. A reader of the home reads contractors and downloads
the contact file; writing needs a role that writes; a contractor of another home is a 404,
for the contact file too. Creating, changing and deleting one is recorded in the audit log
by name (never the note or the contact details). The export and the erasure of a home cover
the new fields.

**Contact file.** `GET /h/<home>/contractors/<id>/contact.vcf` (and
`.../contractors/<id>/vcard/` in the API) returns a vCard **3.0** (RFC 2426), as
`text/vcard; charset=utf-8` with `Content-Disposition: attachment` and a file name made of
ASCII letters, digits and hyphens. 3.0 and not 4.0 (RFC 6350): Apple Contacts and Google
Contacts, which both export 3.0 themselves, Android, Outlook and Thunderbird all import it,
while 4.0 is read with gaps by some of them, and nothing here needs what 4.0 adds (the
properties used, `FN`, `N`, `TITLE`, `TEL`, `EMAIL`, `ADR`, `NOTE`, `UID` and `REV`, are the
same in both). Every value is escaped (backslash, semicolon, comma, and a line break written
`\n`), stripped of control and invisible characters, and lines are folded at 75 octets on
character boundaries, so that a name or a note can never start a line of its own. The
telephone number is checked on the way in (digits, spaces and `+ ( ) - . /`), which also
keeps the `tel:` link of the sheet safe.

## Consequences

- API clients that wrote `open_walls` or the `contract` field must use the new names; exports
  carry them too.
- A list is not extensible by the household: a missing value is "Other" plus text. A list that
  grows is a change of the code, translated for all.
- The household page and the member filters name people without their address; an
  administrator who wants an address finds it on the sheet of the member (owners) or in the
  administration site.
- Two members who share a display name are told apart in the lists by their address in
  brackets. Elsewhere they look alike; the sheet of a member tells them apart. The name is a
  courtesy, not an identity.
- Changing the hemisphere moves the window of the tasks on a predefined season, not their due
  dates: an occurrence already dated stays where it is.
- A contractor is found by name inside a home. Two contractors with the same name stay
  possible (edited by hand); the single field then picks the oldest, and the sheet of the
  other is reached from the list.
