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
application (at that date Babel only came with the documentation group; it became a runtime
dependency on 2026-11-10 for amounts, ADR 0054, and still is not used to compile
catalogs), and one more dependency would need its own decision (ADR 0001). The catalogs are also kept
free of what changes at every run: `makemessages` (the project's own command in
`housecairn.core`) writes no source locations, no line wrapping and no
`POT-Creation-Date`, and `scripts/build_docs.py --update-catalogs` drops that
date from the documentation catalogs. A test fails when the French page is not
served translated, and another when regenerating the catalog changes it.

**Amendment, 2026-11-09: one catalog per app.** With a single
`src/housecairn/locale/fr/LC_MESSAGES/django.po`, two pull requests that each
added strings still conflicted on it, at their neighbouring entries, so every
merge sent the next pull request back for a refresh. Each Django app now has its
own catalog, `<app>/locale/fr/LC_MESSAGES/django.po`, listed in `LOCALE_PATHS`
(`core` first, before the catalogs of allauth and Django). The project's
`makemessages` sends each string to the catalog of the app that owns its file:
the app's directory, or `templates/<app>/`; the shell, the shared templates and
the project modules go to `core`. `--app <name>` limits it to one app. Two pull
requests that add strings to two apps change two files; two strings added to
the same app may still conflict, and the two sides are kept. A string used by
two apps is in both catalogs, and `check_translations` fails when its
translations differ, since only one of them would be shown; `--sources` reports
a missing string with the catalog it belongs to. The single catalog was split by
`scripts/split_catalogs.py`, which checks that the pairs of string and
translation are the same before and after; it can be run again on a branch that
still adds strings to the former catalog. The paths of the single catalog given
above describe the state before this amendment.
