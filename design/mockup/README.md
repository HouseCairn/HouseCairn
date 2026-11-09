# Mock-up v2

`housecairn-maquette-v2.html` is the visual mock-up the maintainer validated before
the first interface was built. It is the visual reference of every screen
([ADR 0017](../../docs/adr/0017-visual-system-and-brand.md)): a screen that departs
from it records the deviation and its reason in a decision record, as ADR 0017 does
for contrast.

- **For the look**, the values in [`design/tokens.json`](../tokens.json) win over
  the mock-up: they carry its palette and sizes, corrected where WCAG 2.2 AA required
  it.
- **For the structure** (sections, tabs, return, actions in place), the navigation
  prototype in [`design/navigation/`](../navigation/README.md) and
  [ADR 0053](../../docs/adr/0053-target-navigation-and-return-rule.md) win over the
  mock-up.

The file is self-contained: open it in a browser, it loads nothing from another
host. It is in French, its data invented. It is kept as validated and not edited; a
new mock-up would be a new file, with its own validation.
