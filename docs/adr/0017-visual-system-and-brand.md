# 0017. Visual system, brand and application shell

- Status: accepted
- Date: 2026-11-07
- Supersedes: the font and colour clauses of [0009](0009-design-tokens.md)

## Context

The first interface lagged behind the v2 mock-up the maintainer had validated: no
logo, system fonts, a header that looked like a prototype, a sign-in page loaded
with options. The business screens of the next milestone build on whatever is
laid down now, so the visual foundation comes first.

## Decision

**Name.** The name shown to a human is **HouseCairn** (interface, page titles,
manifest, one-time-password issuer, API documentation, README, contributing guide).
Technical identifiers stay lower case: `housecairn` (package, image, `HOUSECAIRN_*`
variables, addresses). `NOTICE` and `CLA.md` are legal texts and are not edited in
this change.

**Tokens.** `design/tokens.json` stays the single source and now carries the
mock-up values: the palette (slate, sand, sage, stone, soft tints, status colours),
the Manrope and JetBrains Mono stacks, a type scale, spacing, radii (10, 12, 14,
22 px), two shadows and a `layout` group (44 px touch target, content width,
navigation width). Names follow the existing `--hc-<group>-<name>` scheme.

**Fonts.** Manrope (text) and JetBrains Mono (code) are self-hosted as Latin-subset
variable WOFF2 files under `static/fonts/`, with their SIL OFL 1.1 texts, declared
in `static/css/fonts.css` with `font-display: swap`. A test pins their SHA-256.
Nothing is requested from another host ([0011](0011-no-external-resources-and-csp.md)).

**Deviations from the mock-up, all for WCAG 2.2 AA.** A test computes the contrast
of every text and component pair of the tokens (4.5:1 for text, 3:1 for borders of
controls and the focus ring):

- muted text `#4F605C` instead of `#66736F` (4.1:1 on the tinted backgrounds);
- control borders use `border-strong` `#7A8783` (3.7:1) instead of the decorative
  hairline `#E3DED6` (1.3:1), which stays for cards and separators;
- overdue and error text `#9A3F1D` instead of `#B4532F` (4.0:1 on its tint);
- the focus ring is slate, 3 px, offset 2 px, instead of sand (2.3:1 on white).

**Theme.** Light only: the mock-up has no dark theme. Adding one later means a
second set of token values, not new components.

**Shell.** One `<nav>` with three entries (Home, Homes, More), rendered once and
laid out by CSS: a tab bar fixed at the bottom on a phone (48 px targets, icon and
label, safe-area padding), a column on the left from 56 rem. The app bar carries
the brand and an empty `header_actions` block (the documentation link goes there).
Signed-out pages have no navigation: the wordmark centred above one panel. The page
title is the `h1` of the content, not a second heading in the bar. Entries after
the daily ones live on the **More** page, as in the mock-up. The entries and the
column changed with the amendment of 2026-11-09 below.

**Components.** Plain CSS in `static/css/app.css`, no framework: cards, lists and
rows, buttons (primary, secondary, sand, danger, icon), fields, badges (pills),
alerts and messages, a segmented control, chips, code blocks. Django-allauth
renders plain tags; its `element` templates (button, provider, alert, badge,
panel) are overridden under `templates/allauth/elements/` so its pages share the
look. Icons are inline SVG from `templates/components/icon.html`. No inline style
and no inline script anywhere.

**Files.** `static/css/app.css` is the entry point: it only imports, from the same
directory and in this order, `base.css` (reset, typography, focus), `shell.css`
(app bar, navigation, content area, signed-out layout), `components.css` and
`utilities.css` (rules over everything else, such as reduced motion), after the
`tokens.css` and `fonts.css` that `base.html` loads first. No build step: the
static files storage rewrites each `@import` to the hashed file name. The order is
the original cascade order, shell before components, because some components
refine a shell rule of the same specificity (`.chevron` after `.icon`). The shell's
markup is in `templates/base.html`, which includes `templates/shell/brand.html`,
`help_link.html` and `navigation.html` (the tab bar on a phone and the column on a
computer are the same `nav`); the `header_actions`, `main_class` and `content`
blocks stay in `base.html`, since a block inside an included template cannot be
overridden.

**Brand files.** Sources in `design/brand/` (with the trademark note), served
copies in `static/img/brand/`: wordmark, icon, favicons, `apple-touch-icon`, 192
and 512 px icons. The web manifest is a view (`/manifest.webmanifest`) because the
icon addresses carry a content hash in production.

**Errors.** `400`, `403`, `403_csrf`, `404` extend the shell; `500` is standalone
(no session, no database, no form) because it is shown when the application failed.

**Evidence for review.** The workflow `ui.yml` (not a required check) starts a
throwaway instance, takes screenshots of the main screens on a phone and a desktop in
English and French, and attaches them to the run. Playwright is installed for that
job only, from the `docs` dependency group locked in `uv.lock`
([0016](0016-documentation-site.md)); it is not a dependency of the application. The
documentation job keeps its own screenshots (the pages of the site) as an artifact too.

**Screens of the mock-up not built yet.** Household, API tokens, notifications,
integrations, data, onboarding, and every business screen: they do not exist in the
application yet and arrive with their own features. Screens that do exist (home,
homes, a home, more, about, sign-in, sign-up, password reset, second factor,
passkeys, security keys, recovery codes, e-mail, password, third-party connections,
errors) use the shell.

## Consequences

- A colour or size change is a JSON edit plus the regenerated CSS; the contrast
  test fails if it breaks AA.
- Two font files (about 65 kB) are part of the image and cached for a year.
- The v2 mock-up is the reference for every later screen; a deviation is recorded
  here or in a later record, with its reason.

## Amendment, 2026-11-08: no screenshots in CI

The `ui.yml` workflow no longer takes or uploads screenshots (`ui-screenshots`
artifact), until one dedicated change before the first public release
([0016](0016-documentation-site.md), amendment of the same date). Its job keeps the
end-to-end passkey sign-in and the one-click single sign-on check
([0018](0018-sign-in-page-and-passkeys.md)), and is now named
`Passkey and single sign-on` (it was `Screenshots and passkey sign-in`; it is not a
required check). "Evidence for review" above describes the state before this
amendment.

## Amendment, 2026-11-09: five sections, tabs per section, More in groups

The bar had grown to six entries (Home, Homes, Rooms, Tasks, Stock, More) while
Projects and Budget, two of the four questions of the product, were tabs of Tasks,
off screen on a phone. The navigation audit of the same date (findings NAV-01,
NAV-03, NAV-06, NAV-09) and the maintainer's decisions replace the shell clause:

- **Five sections, one per question**: Today (what to do), Rooms (where), Projects
  (which works), Budget (how much) and More, as in the v2 mock-up. On a phone they
  are the bar at the bottom. From 56 rem the same `nav` is the column on the left:
  the first four sections, then the content of More unfolded under them, without a
  page in between, and sign-out last; the More entry itself is hidden there.
- **The current entry follows the tree**: a page belongs to the section whose root
  leads to it (`core/context_processors.py`, `nav_section`). Budget marks Budget;
  the stock marks Rooms; the calendar marks Today; the contractors, the display
  preferences, the calendar feeds, the pages of a home (settings, household,
  reports, QR labels) and the account pages mark More.
- **Tabs switch between sister views of one section**, four at most, all visible at
  360 px (`core/templatetags/tabs.py`): Today, All, Calendar; Rooms, Stock;
  In progress, Ideas, Finished; Summary, Rooms, Projects, Upkeep. The history is
  the **Done** filter of All, and its address redirects there. A page shows one row
  of tabs at most.
- **A section root has no back link**: Today, All, Calendar, Rooms, Stock, the
  three project lists, the four budget views and More. Every other page keeps one.
- **More comes in four groups** (`core/more.py`): Home (about the home being
  viewed), Me, Instance (administrators only) and Help. An action that cannot be
  taken back is at the bottom of its own page, never on More: deleting the account
  moved to Security and sign-in (`/more/security/`).

Out of this amendment, in later changes: the return to the screen of origin
through a safe `next`, the single home screen, actions in place and the selector
of the current home. Until then, a page reached from another section marks the
section of its own place in the tree.
