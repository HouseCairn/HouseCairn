# 0059. One date format per language, and a decimal field that says what it expects

- Status: accepted
- Date: 2026-11-11
- Extends: [0013](0013-internationalization.md) (dates, numbers and currencies are localized),
  [0054](0054-amounts-with-babel.md) (amounts)

## Context

A test of an instance by someone outside the project showed, on the page of a task in English,
`Nov. 8, 2026` next to `02/08/2027`. The templates asked Django for `DATE_FORMAT` in some
places and `SHORT_DATE_FORMAT` in others, and the short format of English is `m/d/Y`, which a
reader outside the United States takes for 2 August. The same test typed `12,5` in a quantity
in English and got "Enter a number.", without a word on the format expected; the quantity
fields, unlike the money fields, did not even follow the language for the decimal mark.

## Decision

- **One module writes dates.** `housecairn.core.dates` has the four formats the application
  uses: a date (`day`), a date and time (`moment`), a date without its year (`month_day`) and a
  date with its weekday (`weekday_day`). They are the formats of the Unicode CLDR, drawn by
  Babel from the locale of the language being served, as the amounts are (ADR 0054): `Nov 8, 2026`
  in English, `8 nov. 2026` in French. The month is always in letters; no format has the day
  and the month in digits. The templates use the filters of `core.templatetags.dates`
  (`|day`, `|moment`, `|weekday_day`), the code calls the functions. `|date:` stays for
  machine values (`Y-m-d` of an input) and parts of a calendar (`F Y`, a weekday name).
- **Babel rather than the formats of Django.** Django's French abbreviations of months are not
  the usual ones (`jan.`, `fév.` where French writes `janv.`, `févr.`), its English `DATE_FORMAT`
  is `Nov. 8, 2026` but its French one `8 novembre 2026`, and a `FORMAT_MODULE_PATH` is a
  setting that fixes the format of a language instead of the choice of a screen. CLDR gives the
  right form for every language Babel knows, with no string to translate in our catalogs.
- **A test keeps it so.** `tests/test_dates.py` fails when a template formats a date with
  something else than the allowed list, when the code asks for a short format, and when a
  screen of a task shows a date with the day and the month in digits, in either language.
- **One class for decimal numbers.** `core.forms.DecimalMarkField` is localized (the mark
  follows the language: `12.5` in English, `12,5` in French). Where the mark is a point, a
  comma is still refused, since it also groups thousands (`1,250.50`) and guessing would
  record a wrong amount, but the message names the expected format. `MoneyField` and the new
  `QuantityField` are built on it, and a test fails for any other decimal field of any form.
  The number box of the browser (`type="number"`), which follows the language of the system
  and not the one of the page, is replaced by a text box with `inputmode="decimal"`.

## Consequences

- The notifications (`notifications/reminders.py`) still ask Django for `DATE_FORMAT`: a month
  in letters, never a numeric date, but `Nov. 8, 2026` and `8 novembre 2026` instead of
  `Nov 8, 2026` and `8 nov. 2026`. They move to `core.dates.day` in a later change.
- The date boxes (`type="date"`) are drawn by the browser, in the habits of the system. The
  value sent is always ISO 8601.
- The import of CSV keeps its own rules (ISO dates and dot decimals, documented with the
  files).
