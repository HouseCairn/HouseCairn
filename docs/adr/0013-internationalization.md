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
- The catalog lives in `src/housecairn/locale/fr/LC_MESSAGES/django.po`; the
  compiled `django.mo` is committed so the application runs without GNU
  gettext installed.
- `manage.py check_translations` fails on an untranslated or fuzzy entry;
  `--sources` also runs `makemessages` (needs GNU gettext) and fails if a string
  of the code or templates is missing from the catalog. Both run in the tests,
  the second when gettext is available.
- Dates, numbers and currencies are formatted with Django's localization.

## Consequences

- A pull request that adds a string also updates `django.po` and `django.mo`:

  ```sh
  cd src/housecairn
  uv run python ../../manage.py makemessages -l fr --no-obsolete --add-location=file -i "static/*"
  uv run python ../../manage.py compilemessages -l fr
  ```
