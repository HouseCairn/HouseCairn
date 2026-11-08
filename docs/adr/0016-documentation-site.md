# 0016. Documentation site

- Status: accepted
- Date: 2026-11-07

## Context

HouseCairn is installed and used by people who will not read its code. They need
a public documentation site, in English and French, that is always the one of
the code they run, that loads nothing from other hosts (ADR 0011), and whose
screenshots and API reference cannot go stale. The site is published at
<https://docs.housecairn.app> by GitHub Pages, from this repository.

## Decision

### Tool: Sphinx with Furo and MyST

The first plan was MkDocs with the Material theme. The maintenance of the
candidates was checked on 2026-11-07, before writing any file:

| Tool | State on 2026-11-07 | License |
| --- | --- | --- |
| MkDocs 1.x | Last release 1.6.1 on 2024-08-30; the repository is closed to outside contributions since 2026-10-02. The Material team writes that MkDocs 1.x is unmaintained and that it is unclear whether security issues will be addressed ([announcement](https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/)). MkDocs 2.0 (pre-release) drops plugins and is incompatible with Material. | BSD-2-Clause |
| Material for MkDocs | In maintenance mode since 2025-11-05 (9.7.0, "final version"): critical and security fixes only, end of life on 2027-05-05 ([Zensical, upcoming changes](https://zensical.org/upcoming-changes/)). The publisher recommends evaluating Zensical. | MIT |
| Zensical | Version 0.1.0 of 2026-11-05, out of its 0.0.x alpha series; same team as Material, reads `mkdocs.yml`. No i18n plugin: one language per build ([plugin compatibility](https://zensical.org/docs/compatibility/mkdocs/plugins/)). Public interfaces still moving. | MIT |
| ProperDocs | A fork of MkDocs 1.x, 1.6.7 of 2026-03-20; does not settle the end of life of Material. | BSD-2-Clause |
| Sphinx | Maintained: 9.1.1 released on 2026-10-20 ([PyPI](https://pypi.org/project/Sphinx/#history)); gettext translation built in. | BSD-2-Clause |

MkDocs 1.x has no security maintenance and Material ends in six months, so the
choice went to the maintainer, who chose **Sphinx with the Furo theme and MyST
(Markdown)**: a mature tool, translations by gettext (the format Weblate reads,
so nothing to convert later), no plugin to depend on for translation or search.
Zensical was not chosen: version 0.1.0, no i18n. Reconsider it once it has a
stable release and a translation story.

Pages are Markdown (MyST), the existing `install.md` and the ADRs included. The
ADRs are part of the site as they are, in English only.

### Build

`docs/conf.py` configures Sphinx; `docs/_ext/housecairn_docs.py` is the project's
small extension (below). `scripts/build_docs.py` builds both languages:

- the strict build is `sphinx-build -W --keep-going -n` (warnings are errors,
  nitpicky mode checks every cross reference), with the `dirhtml` builder
  (`/page/` addresses);
- English is at the root of `docs/_build/site`, French is built with
  `-D language=fr` under `/fr/`;
- a Markdown link to a repository file outside `docs/` (`SECURITY.md`,
  `deploy/production.env.example`) is rewritten at read time to the file on
  GitHub, so the files keep working when browsed on GitHub.

The installation page of the first lots, `docs/install.md`, is split, without
duplication, into `getting-started/install.md`, `getting-started/first-start.md`,
`administration/` (variables, backup, update, hardening) and
`security/verify-image.md`; the other pages of the tree (`guides/`, `screens/`,
`api/`, `integrations/`, `developer/`, release notes) say honestly what does not
exist yet. ADR 0015 still names `docs/install.md` in one sentence: a record is
not rewritten.

### Dependencies and licenses

The `docs` group of `pyproject.toml`, locked in `uv.lock` (hashes included),
installed with `uv sync --locked --group docs`. It is not part of the image or
of the application's runtime, and nothing of it is linked into the application,
so the licenses of ADR 0014 apply to what ships; they are still all in the
allowed list, except as noted.

| Package | Locked version | License |
| --- | --- | --- |
| sphinx | 9.2.0 | BSD-2-Clause |
| furo | 2025.12.19 | MIT |
| myst-parser | 5.1.0 | MIT |
| sphinx-intl | 2.4.0 | BSD-2-Clause |
| playwright | 1.64.1 | Apache-2.0 |
| docutils | 0.22.4 | Public domain, BSD-2-Clause for some modules (see the exception below) |
| babel, accessible-pygments, idna, click, markupsafe, snowballstemmer | see `uv.lock` | BSD-3-Clause |
| jinja2, alabaster, sphinxcontrib-* | see `uv.lock` | BSD (2 or 3 clauses) |
| markdown-it-py, mdit-py-plugins, mdurl, sphinx-basic-ng, beautifulsoup4, soupsieve, pyyaml, imagesize, charset-normalizer, urllib3, pyee, greenlet | see `uv.lock` | MIT (greenlet: MIT and PSF-2.0) |
| requests, packaging | see `uv.lock` | Apache-2.0 (packaging: Apache-2.0 or BSD-2-Clause) |
| pygments | 2.21.0 | BSD-2-Clause |
| certifi | 2026.10.23 | MPL-2.0 |
| roman-numerals | 4.1.0 | 0BSD or CC0-1.0 |
| typing-extensions | 4.16.0 | PSF-2.0 |

**docutils needs an exception in the dependency review.** Its license scan finds
`BSD-2-Clause AND BSD-3-Clause AND CC-PDDC AND GPL-1.0-or-later AND GPL-3.0-only
AND GPL-3.0-or-later AND LicenseRef-scancode-other-copyleft AND
LicenseRef-scancode-public-domain`, which no entry of the allowed list matches.
Read from its `COPYING.rst`: most of docutils is dedicated to the public domain,
three modules are BSD-2-Clause, and the files that were part of the GPL-3.0
project eLyXer carry a copy of the GPL text because their author relicensed them
to BSD-2-Clause for docutils. Nothing in it is GPL-only, and it is not
distributed with HouseCairn (documentation build only). `dependency-review.yml`
therefore allows the package `pkg:pypi/docutils` (any version) by name, and no
other. Every other package of the `docs` group passed the review with the
existing list.

Sphinx 9.2 requires Python 3.13 ([PyPI](https://pypi.org/project/Sphinx/9.2.0/),
`Requires: Python >=3.13`). The project was on 3.12 when this ADR was written, so
the `docs` group first asked for `sphinx>=9.1.1`, locked at 9.1.1, and
Dependabot ignored the minor and major updates of `sphinx`. Since the project
moved to Python 3.13 (ADR 0015, `requires-python`), the group asks for
`sphinx>=9.2`, locked at 9.2.0, the strict build passes with it, and Dependabot
proposes Sphinx updates like any other.

### Languages

English is the source. French is a set of gettext catalogs, one per page, in
`docs/locale/fr/LC_MESSAGES/`, produced by `sphinx-build -b gettext` then
`sphinx-intl update` (`scripts/build_docs.py --update-catalogs`) and committed;
this is the format Weblate will read later, no integration is added now. The
site and the catalogs follow these rules:

- the arborescence is the same in both languages, and a language switcher in the
  sidebar links each page to the same page of the other language;
- a string without translation is shown in English (gettext's behavior). A French
  page that is not entirely translated says so in a notice at its top, with the
  proportion computed by Sphinx; an ADR page, which is English only by decision,
  therefore carries that notice;
- the build fails when a catalog lacks a string of its page, or keeps a string
  that was removed, so catalogs cannot lag behind the pages. The ADRs have no
  catalog.

### No external resource

Furo loads nothing from another host by default (system fonts, inline icons).
`scripts/check_docs_site.py` parses every HTML and CSS file of the built site and
fails on a URL loaded as a resource from another host: `script`, `img`,
`source`/`srcset`, `iframe`, `object`, `embed`, `video`, `audio`, `track`,
`<link>` with a loading `rel` (stylesheet, icon, preload, preconnect, manifest...),
SVG `image` and `use`, CSS `url()` and `@import` in files, `<style>` and `style`
attributes, an external `<base href>`, a `<meta http-equiv="refresh">` to an
absolute address, and `fetch()`, `import()`, `new WebSocket()`, `new EventSource()`
or `XMLHttpRequest.open()` with an absolute URL written as a literal in the
built `.js` files (an address built at run time is out of reach of this check;
the content security policy of ADR 0011 is the net below it). Outgoing `<a>` links are allowed. Search is Sphinx's own, on a static
index served with the site; there is no analytics. `tests/test_docs_scripts.py`
has a negative test for each kind of resource, so the check is shown to fail.

### Links

Internal links, images and anchors are checked twice: by nitpicky mode at build
time, and by `check_docs_site.py` on the built HTML (every relative target exists
in the site, every `#anchor` exists on its page). External links are checked by
`sphinx-build -b linkcheck`, with retries, in a separate job named
**`Documentation (external links)`** of `docs.yml`, on pull requests and every
Monday on `main`. It is deliberately not a required check: it depends on sites
we do not control, and a passing outage of one of them must not block every pull
request; it still fails visibly. Everything deterministic stays in the required
`Documentation` job. Examples at `example.com` and `localhost` are skipped, and
so is the site's own address: it answers nothing before its first publication.

### API reference

The `openapi-reference` directive of the extension runs `manage.py spectacular
--validate --fail-on-warn` at each build, writes `docs/_generated/openapi.json`,
and renders every operation (parameters, request body, responses) and every
schema as plain HTML tables: no Swagger UI, no ReDoc, no JavaScript. The raw
schema is a download of the site. `check_docs_site.py` reads the same schema and
fails if the reference page of either language lacks the anchor of an operation
(`operation-<operationId>`); the build reports the count (`4/4`).

### Screenshots

`scripts/docs_screenshots.py` starts the application on a throwaway SQLite
database with generated data only (one demonstration account at `example.com` with
a random password, two made-up homes), and takes the existing screens (sign-in,
start page, list of homes, one home) with Playwright's Chromium, in English and
French, on a computer (1280 px) and on a phone (390 px, 2x). The images are
written to `docs/_generated/screenshots/`, ignored by git: they can be generated,
so they are not committed (a committed image would go stale silently and make
reviews noisy). Sphinx picks `name.fr.png` for the French site.

The script reaches each page by its address (the identifier of the first home is
read from the seed), never by the text of a link, so a new navigation entry or a
second occurrence of a name cannot break it. When a step fails it prints the
address and title of the page, keeps `failure-<device>.png` next to the other
images and prints the end of the server log; the workflow uploads the partial
set even then, and the step that follows no longer hides this error. The job runs
on every pull request and on `main`: a failure only seen after a merge is flaky,
not path dependent, and the failure image is what tells why.

The browser comes from `playwright install --with-deps --only-shell chromium`, the
official command of the Playwright version locked in `uv.lock`: it downloads
Chrome Headless Shell (Chrome for Testing, revision named in the `browsers.json`
of the locked wheel) from Playwright's CDN (`cdn.playwright.dev`) over HTTPS, and
system libraries from the runner's Ubuntu repositories. **Playwright checks the
size of the download, not a checksum**: the integrity of the browser rests on
TLS and on the pinned version, not on a digest pinned by this repository. The
exposure is small: the job has a read-only token and no secret, the browser only
opens a server on `127.0.0.1` with generated data, and it never loads a page of
another host. The Python package itself is verified by the hash in `uv.lock`.

### Help link

Each screen of the application has a discreet **?** link in the top bar, to its
page of the documentation site, in the language of the interface. The base
address is `HOUSECAIRN_DOCS_URL` (default `https://docs.housecairn.app`); it is a
link only, the application loads nothing from it, so ADR 0011 holds.
`housecairn.core.help` maps each web route to its page; routes of django-allauth
share the account page. `tests/test_help_links.py` fails if a route of the
application is neither mapped nor declared as not being a screen (API, health
check, administration), if a mapped page has no source file, and, in CI, if its
page is missing from the built site in either language.

### Workflows

`docs.yml`:

- on `pull_request` and on `push` to `main`, the job named **`Documentation`**:
  locked install, browser, screenshots, strict build in both languages,
  `check_docs_site.py`, the tests of the site, of the help links and of the
  scripts (with the built site), the external link check is a separate job, see below;
- on `push` to `main` only, the site is packaged by `actions/upload-pages-artifact`
  and the job **`Publish documentation`** deploys it with `actions/configure-pages`
  and `actions/deploy-pages`, in the `github-pages` environment. Its token has
  `pages: write` and `id-token: write`; `pages: write` is held by no other job
  of the repository (`id-token: write` is also held by the image and Scorecard
  jobs); the build job has `contents: read` only.

Both follow ADR 0014: full commit SHAs with the tag in a comment, checked with
`git ls-remote`; `permissions: {}` at the workflow level; `persist-credentials:
false`; no event value interpolated into a `run:`; `concurrency`. The Pages
deployments are queued, never cancelled.

**Third-party actions: none added.** The three Pages actions, `actions/checkout`
and the `actions/upload-artifact` that `upload-pages-artifact` uses internally
are published by GitHub; `astral-sh/setup-uv` is already on the organization's
list (ADR 0014).

| Action | Pinned version |
| --- | --- |
| `actions/configure-pages` | v6.0.0 |
| `actions/upload-pages-artifact` | v5.0.0 |
| `actions/deploy-pages` | v5.0.1 |

### The documentation changes with the code

`CONTRIBUTING.md` and the pull request template state the rule. The check is the
job **`Documentation updated`** of `docs-updated.yml`, which runs
`scripts/check_docs_updated.py`: a pull request that changes a view, a URL
route, a form, a serializer, an API module, a template, the settings or the
example deployment files (`compose.yaml`, `deploy/*.example`, `.env.example`)
and changes nothing under `docs/` fails. The escape hatch is the label
`no-docs-needed`, added by the maintainer (the workflow also runs when a label
is added or removed). The rule only looks at file paths, which is the simplest
mechanism that does not need to understand the change; Dependabot's
own pull requests are exempt (author `dependabot[bot]`, read from the pull
request author by the workflow, never from a label or a branch name): they bump
the postgres image in `compose.yaml`, which changes no screen and no setting. No
other account is exempt.

### Checks to require on `main`

Once each has run once on `main` or on a pull request (a check that never ran
blocks every merge), add to the ruleset, in this order:

- `Documentation`
- `Documentation updated`

`Publish documentation` is not required (it runs on `main` only).

## Consequences

- The site is rebuilt and published on every merge to `main`; screenshots and
  the API reference are those of that commit.
- Before the first publication, GitHub Pages must be set to deploy from GitHub
  Actions, and the `no-docs-needed` label must exist: both are repository
  settings, made by the maintainer. Publication to
  `https://docs.housecairn.app` can only be verified after the first merge.
- A change to a French page's text means updating its catalog; the build says
  which. Translation by a tool such as Weblate can replace the hand editing
  without changing the files.
- A new screen needs a page of the screen reference and an entry in
  `housecairn.core.help`, or the tests fail.
- Zensical is to be reconsidered when stable and translatable.

## Amendment, 2026-11-07: design of the site

**Why.** The first site used Furo's default look. The maintainer decided to keep
Sphinx, Furo, MyST and gettext, and to give the site the identity and the finish
of the application ([ADR 0017](0017-visual-system-and-brand.md)) without forking
the theme or loading anything from another host.

**Theme.** Furo is customized only through its CSS variables and one stylesheet,
`docs/_static/housecairn.css`, plus three small templates in `docs/_templates/`
(the page, the sidebar brand, the language switcher). Nothing is duplicated from
the application: `conf.py` copies into the site, at build time, the generated
`tokens.css` (from `design/tokens.json`), the Manrope and JetBrains Mono WOFF2
files with their SIL OFL 1.1 texts, the wordmark, the favicons and the
wordmark for dark backgrounds of `design/brand/`. The stylesheet maps the tokens
to Furo's variables: palette, Manrope for text and JetBrains Mono for code,
radii (10 to 14 px), spacing, the application's white panels with a hairline
border and a soft shadow on its warm background. Code blocks, admonitions,
tables, screenshots (frame, radius, shadow, caption) and the API reference
follow the same panels. The application is light only; **the site also has a
dark theme**, Furo's automatic, light and dark switch, with the brand colours on
slate (`slate-deep` page, `slate` sidebar, sand links). Its values are in the
stylesheet, next to the light ones, and are checked like them (below). Code
colours are Pygments' `a11y-light` and `a11y-dark` styles, built for AA contrast.

**Home page.** `docs/index.md` is an entry page, not a table of contents: a
short pitch, an honest status box, six cards (Getting started, Guides, Screen
reference, API, Administration, Security), a screenshot of the application, and
the table of contents hidden (the sidebar shows it). The cards are MyST
`container` blocks and plain CSS, so their text stays in the gettext catalogs;
`sphinx-design` was not needed for a grid of six links and is not added.

**Navigation.** Breadcrumbs, then at the bottom of each page "Edit this page on
GitHub" and "Report a problem with this page" (the bug form, titled with the
page), a footer with the licence, the trademark reservation of `NOTICE` and the
AI disclosure. The language switcher stays at the top of the sidebar, as a
segmented control. These strings are in the language of the build, from
`UI_STRINGS` in the extension, so the page catalogs stay one per page. Search is
still Sphinx's own local index.

A code block or a table wider than the page scrolls sideways; a small script,
`docs/_static/housecairn.js`, gives it `tabindex="0"` so that it can be reached
and scrolled with the keyboard (WCAG 2.1.1, found by axe-core's
`scrollable-region-focusable` rule, see the cross-check below).

**Translation notice.** Sphinx translates the alternative text of an image but
leaves the image marked as untranslated, so every French page with a screenshot
said it was not entirely translated. Two transforms of the extension (before
and after Sphinx's `Locale`) count an image as translated when its alternative
text was; an image whose text has no translation still counts as untranslated.

**Dependency added: `sphinx-copybutton` 0.5.2 (MIT)**, a copy button on code
blocks, with its French labels. Publisher: Executable Books, who also publish
`myst-parser`. Its last release is 0.5.2 of 2023-04-14; its repository still
receives changes (2025-04, 2026-06) and it works unchanged with Sphinx 9.2. It
is small (one script, one stylesheet, the bundled `clipboard.min.js`, MIT) and
loads nothing from another host (`check_docs_site.py` passes). It was preferred
to an in-house script because it already handles prompts, line numbers and
console output, which are excluded from the copy (`copybutton_exclude`). If it
stops working with a future Sphinx, the replacement is a few lines of
JavaScript with `navigator.clipboard`.

**Accessibility, checked by a tool.** `scripts/check_docs_design.py` serves the
built site on `127.0.0.1` and opens it in Playwright's Chromium (already used for
the screenshots):

- **contrast** (WCAG 2.2 AA, 1.4.3): every visible text element of every page, in
  both languages and both themes, against the background it is drawn on (computed
  colours, translucent layers blended): 4.5:1, 3:1 for large text. A text on a
  background image would be reported as not measured; there is none;
- **focus** (2.4.7 and 1.4.11): from the top of the home page, the Tab key reaches
  the skip link first, and each focused element shows an outline of 2 px or more
  with 3:1 against the page (3 px, slate in light, sand in dark);
- **motion** (2.3.3): with `prefers-reduced-motion: reduce`, nothing on the home
  page has a transition or an animation;
- **screenshots** of the home page, a guide, the API reference and a screen page,
  light and dark, computer and phone, English and French (32 images), written to
  `docs/_build/site-screenshots/`, outside the published site, and attached to
  the run as the `docs-site-screenshots` artifact for review.

It runs in the `Documentation` job, after `check_docs_site.py`; the job keeps
its name. Its arithmetic (contrast ratio, blending, large text, focus rule) is
unit-tested in `tests/test_docs_scripts.py`.

As a cross-check when this change was made, axe-core 4.14 (WCAG 2.0 to 2.2, A
and AA rules) was run once outside the repository on all 102 pages, light and
dark, computer and phone: no violation after the script above. axe-core is not
added as a dependency: it would bring an npm toolchain into the job for a check
the script above already makes on the criteria that the design can break.

## Amendment, 2026-11-08: no screenshots in CI

The CI takes no screenshot any more, for the site or for review, until one
dedicated change before the first public release. The step that photographed a
demonstration instance (`scripts/docs_screenshots.py`) failed intermittently:
the session was lost after signing in on the phone pass, and the page then timed
out. As a required check, it held up unrelated pull requests.

- The `Documentation` job keeps its name, the strict build in both languages,
  `check_docs_site.py`, `check_docs_design.py` (contrast, focus, motion) and the
  tests. It no longer starts the demonstration instance, takes or uploads the
  `docs-screenshots` images, or writes the `docs-site-screenshots` images of the
  built site. The browser stays: `check_docs_design.py` needs it.
- `Documentation (external links)` no longer installs the browser nor takes
  screenshots: the build has no image to embed.
- The pages no longer embed `/_generated/screenshots/` images; the
  `img.screenshot` styles and the extension that counts a translated alternative
  text as translated stay for the dedicated change.
- `scripts/docs_screenshots.py` is removed; it stays in the history of the
  repository for that change. Playwright stays in the `docs` group: the design
  checks and the passkey sign-in of `ui.yml` use it.

The sections "Screenshots" and "Workflows" above and the screenshots of
`check_docs_design.py` describe the state before this amendment.
