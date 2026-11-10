# 0054. Amounts written by Babel, with the symbol of the currency

- Status: accepted
- Date: 2026-11-10
- Extends: [0001](0001-record-architecture-decisions-and-dependencies.md) (runtime
  dependencies), [0013](0013-internationalization.md) (internationalization)

## Context

Amounts were written by a filter of the projects app, `money`, as the number of the
language followed by the ISO 4217 code of the currency of the home: `1 250,50 EUR`. The
maintainer decided on 2026-11-09 that every amount reads the same way everywhere, with
the symbol of the currency when the language has one: `1 250,50 €` in French, `€1,250.50`
in English. Three templates (the history of a task, the page of a task, the suppliers of
an item) bypassed the filter and wrote the number and the code by hand.

Django knows how to group and separate digits for a language, but not the symbol of a
currency, nor where it goes (after the number with a no-break space in French, before it
in English), nor how a minus sign is placed.

## Decision

**Babel becomes a direct runtime dependency** (`babel>=2.18`, BSD-3-Clause, already in
`uv.lock` for the documentation group, so the lock gains no package). It carries the CLDR
data, and `babel.numbers.format_currency` gives the exact form of every currency in every
language, symbol or ISO code when the language has no symbol (`SEK` stays `SEK`).

**One filter, in `core`.** `{% load money %}` then `{{ amount|money:currency }}`, in
`housecairn/core/templatetags/money.py`. The filter of the projects app is removed, with
no alias, and every template that wrote an amount by hand now uses it. The language is the
one being served; a language that Babel does not know is written in English.

**Always two decimals**, whatever the currency (`currency_digits=False`), as the fields
accept: the filter must not round a value that the form let through. The `Decimal` is
never turned into a float. A symbol made of letters (`CHF`, `SEK`) is separated from the
digits by a no-break space in every language, which CLDR leaves out in English.

**Unchanged:** the CSV exports and the API carry the raw number with a dot, and the ISO
code in a field of their own (`currency`). They are read by programs, not by people.

## Alternatives

- **A small table of symbols in `core`** (EUR, USD, GBP, CHF...), the ISO code for the
  rest. No dependency, but it diverges from CLDR as soon as it is written (the dollar is
  `$US` in French, `CA$` in English for the Canadian one), and it is code to maintain for
  a result that Babel already gives. Rejected: rule 1, do not reinvent.
- **Django's `localize` alone.** No currency support. Rejected.

## Consequences

- The image embeds Babel (`uv sync --locked --no-dev` installs the direct dependencies).
  The documentation group still lists it, harmlessly.
- A new language needs nothing more than its catalog: Babel already knows the CLDR locales.
- The tests write `€1,250.50` and `1 250,50 €`, with the narrow no-break space that CLDR
  puts between the groups of digits in French.
