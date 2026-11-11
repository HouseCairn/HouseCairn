# Contributing

The rules for contributions (CLA, sign-off, checks, AI-assisted
contributions) are in [CONTRIBUTING.md](../../CONTRIBUTING.md). This page
covers the documentation.

## Documentation changes with the code

A pull request that changes what users see or configure (a screen, an
address, an API operation, a setting) updates this documentation in the same
pull request. The `Documentation updated` check fails when such a change comes
without any change under `docs/`. When no page is concerned, the maintainer
adds the `no-docs-needed` label to the pull request, and the check passes.

## Build the site locally

```sh
uv sync --locked --group docs
uv run playwright install --only-shell chromium   # once
uv run python scripts/build_docs.py
uv run python scripts/check_docs_site.py docs/_build/site
uv run python scripts/check_docs_design.py docs/_build/site
```

The site is in `docs/_build/site/`, English at its root and French under
`fr/`; open `docs/_build/site/index.html` in a browser. The build is strict:
any warning, such as a broken reference, fails it. `check_docs_design.py`
checks the contrast of every page in the light and dark themes, the keyboard
focus and reduced motion.

The site has no screenshots for now, and the CI takes none: they come back in
one dedicated change before the first public release.

Exception: the images of the README (`docs/assets/readme-*.png`) are allowed. They are taken by hand on a local instance with made-up data, never in CI, and no page of the documentation uses them.

## Translations

Pages are written in English. Their French translations are gettext catalogs,
one per page, in `docs/locale/fr/LC_MESSAGES/`. After changing a page, update
the catalogs, then translate the new strings in the `.po` files:

```sh
uv run python scripts/build_docs.py --update-catalogs
```

A string without translation is shown in English, and the French page then
says that it is not entirely translated. The build fails when a catalog lacks
a string of its page, so that the catalogs never lag behind the pages.

The strings of the application itself are in one catalog per app,
`src/housecairn/<app>/locale/fr/LC_MESSAGES/django.po`; the shared strings
(the shell, the common templates) are in the catalog of `core`. Run
`makemessages` from `src/housecairn`, for every app or for one with
`--app <name>`: each string goes to the catalog of the app that owns its file,
so two pull requests that add strings to two apps never touch the same
catalog. The compiled `django.mo` files are built from the catalogs and never
committed: after `uv sync`, and after every change of a catalog, compile them
(this needs GNU gettext):

```sh
uv run python manage.py compilemessages --ignore=.venv --ignore=docs
```

`makemessages` writes the catalog without source locations, line wrapping or
creation date, so that two branches which add strings do not conflict. If a
`.po` conflict remains, keep both sides.

## Release notes

Each pull request adds its own release notes entry, one fragment per
category: `docs/release-notes/unreleased/new/<topic>.md` for a new feature,
`fixed/` for a bug fix, `upgrade/` for what an administrator must do when
updating. Its French translation is in its own catalog, created by
`--update-catalogs`. Never edit `release-notes.md` nor its catalog: the
`Documentation updated` check fails such a pull request. The release notes page
shows the fragments of each category, translated, in the order of their file
names. When a version is published, the maintainer folds them into the page:

```sh
python scripts/release_notes.py fold --version 0.1.0
uv run python scripts/build_docs.py --update-catalogs
```

Then translate the heading of the version in `release-notes.po`.
