# 0009. Design tokens in one JSON file

- Status: accepted
- Date: 2026-11-07

## Context

The web interface and the future iOS app must share colours, typography,
spacing and radii, starting from the logo palette: slate `#1F3A3D`, sand
`#C8A27C`, sage `#8FA39A`, stone grey `#5F726E`.

## Decision

- `design/tokens.json` is the single source: groups `color`, `font`, `space`,
  `radius`, flat names in lowercase with hyphens.
- `manage.py build_design_tokens` generates
  `src/housecairn/static/css/tokens.css` as CSS custom properties named
  `--hc-<group>-<name>`. The generated file is committed and never edited by
  hand; `--check` fails if it is out of date, and a test does the same.
- Fonts are system font stacks: no font file to download, nothing external.
- Text colours meet WCAG 2.2 AA contrast on the background colours; sage and
  sand are used for accents and borders, not for body text.

## Consequences

- A colour change is one JSON edit plus the regenerated CSS, in the same pull
  request.
- A later generator can emit Swift code for the iOS app from the same file.
