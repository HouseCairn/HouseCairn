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
