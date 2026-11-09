# Release notes fragments

Each pull request that changes what users or administrators see adds its own
release notes entry here, instead of editing `docs/release-notes.md`: two pull
requests then never conflict on the release notes nor on their catalog.

- One file per pull request and category: `new/<topic>.md` (a new feature),
  `fixed/<topic>.md` (a bug fix) or `upgrade/<topic>.md` (what an administrator
  must do or know when updating). `<topic>` is short, in lowercase with hyphens,
  for example `new/inspiration-links.md`.
- The file starts with this front matter, then holds the entry as a bullet list,
  without a heading (the category gives it one):

  ```markdown
  ---
  orphan: true
  nosearch: true
  ---

  - **Inspiration links.** A project keeps links to the pages that inspired it...
  ```

- Links are relative to the fragment, as in any page: `../../../guides/projects.md`.
- Its French translation goes in its own catalog: run
  `uv run --group docs python scripts/build_docs.py --update-catalogs`, then
  translate `docs/locale/fr/LC_MESSAGES/release-notes/unreleased/<category>/<topic>.po`.

The release notes page shows the fragments of each category, in the order of
their file names, translated. When a version is published, the maintainer folds
them into the page with `python scripts/release_notes.py fold --version <version>`
([ADR 0016](../../adr/0016-documentation-site.md)).
