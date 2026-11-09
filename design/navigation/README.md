# Navigation prototype

`prototype-navigation.html` is the reference for the **structure** of the
interface: the five sections, their tabs, the content of More, the current home,
the return rule (where each back link and each form leads) and the actions in
place (Done, Skip and Undo without a reload). The maintainer validated it on
**2026-11-09**, together with the target navigation of
[ADR 0053](../../docs/adr/0053-target-navigation-and-return-rule.md).

It is **not** a reference for the look. Colours, type, spacing and components come
from [`design/tokens.json`](../tokens.json) and the components of the application
([ADR 0017](../../docs/adr/0017-visual-system-and-brand.md)); the visual reference
of a screen is the v2 mock-up in [`design/mockup/`](../mockup/README.md). Where the
prototype and the tokens disagree on the look, the tokens are right.

The rules the prototype illustrates are written in the
[design guide](../../docs/developer/design-guide.md), which is the text a pull
request is reviewed against.

## Open it

Open the file in a browser; it needs no server and loads nothing from another host
(no script, style, font or image from elsewhere: the Manrope font is embedded, under
the SIL Open Font License 1.1, as in
[`src/housecairn/static/fonts/`](../../src/housecairn/static/fonts/)). The data in
it is invented. Narrow the window below 56 rem to see the phone layout, widen it to
see the computer column.

## Keep it up to date

The prototype changes with the navigation, in the same pull request:

1. A change that adds a section, a tab or an entry of More, or changes where a back
   link or a form leads, updates the prototype so that it shows the new behaviour.
2. It also updates the section of the design guide that describes the behaviour,
   and, for a new section or a fifth tab, adds a decision record.
3. The file stays self-contained: one HTML file, no external resource, no build
   step, invented data only, no screenshot next to it.
4. The date above is the date of the last validation by the maintainer. Change it
   only when the maintainer has validated the new version, and say so in the pull
   request.
