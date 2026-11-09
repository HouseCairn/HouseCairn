# 0013. English source, French shipped, no hard-coded strings

- Status: accepted
- Date: 2026-11-07

## Context

Housecairn is written in English and ships in French from V1; more languages
will come through a translation platform. Strings added without translation
functions are the usual cause of half-translated screens.

## Decision

- English is the source language (`LANGUAGE_CODE = "en"`); `LANGUAGES` lists
  English and French. `LocaleMiddleware` picks the language from the browser.
- Every user-visible string goes through `gettext` / `gettext_lazy` in Python
  and `{% translate %}` / `{% blocktranslate %}` in templates. The product name
  is not translated.
- The catalog lives in `src/housecairn/locale/fr/LC_MESSAGES/django.po`. The
  compiled `django.mo` is not committed (amendment of 2026-11-09, see below).
- `manage.py check_translations` fails on an untranslated or fuzzy entry;
  `--sources` also runs `makemessages` (needs GNU gettext) and fails if a string
  of the code or templates is missing from the catalog. Both run in the tests,
  the second when gettext is available.
- Dates, numbers and currencies are formatted with Django's localization.

## Consequences

- A pull request that adds a string also updates `django.po`:

  ```sh
  cd src/housecairn
  uv run python ../../manage.py makemessages -l fr -i "static/*"
  ```

**Amendment, 2026-11-09: the compiled catalog is not committed.** Committing
`django.mo` meant that every pull request regenerated a binary file that git
cannot merge, so two parallel pull requests always conflicted on it. The `.mo`
is now ignored by git and compiled wherever the application runs: by
`compilemessages` in the build stage of the image (ADR 0015), in a shared
composite action (`.github/actions/compile-messages`) in every CI job that runs
Django, and by the contributor after `uv sync`. It needs GNU gettext (`msgfmt`),
as `check_translations --sources` already does; the application itself does not
need gettext at run time, since the image carries the compiled file. A pure
Python compiler was not retained: no such tool is a dependency of the
application (Babel only comes with the documentation group), and one more
dependency would need its own decision (ADR 0001). The catalogs are also kept
free of what changes at every run: `makemessages` (the project's own command in
`housecairn.core`) writes no source locations, no line wrapping and no
`POT-Creation-Date`, and `scripts/build_docs.py --update-catalogs` drops that
date from the documentation catalogs. A test fails when the French page is not
served translated, and another when regenerating the catalog changes it.
