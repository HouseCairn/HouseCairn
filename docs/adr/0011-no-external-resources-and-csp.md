# 0011. No external resources, strict CSP

- Status: accepted
- Date: 2026-11-07

## Context

Principle P6: no outgoing call that the operator has not configured. A CDN
would see every page view, and an injected script would see every household's
data. A strict Content Security Policy is the second line of defence after
output escaping.

## Decision

- htmx is vendored in `src/housecairn/static/vendor/htmx/` (version 2.0.11,
  unmodified file from the npm package, integrity recorded in its `README.md`,
  checked by a test, and loaded with a `sha384` `integrity` attribute). Swagger
  UI comes from drf-spectacular-sidecar. Fonts are system fonts.
- django-csp sends, on every response: `default-src 'none'`; `script-src`,
  `style-src`, `font-src`, `connect-src`, `manifest-src` `'self'`; `img-src`
  `'self' data:`; `form-action 'self'` (plus the OIDC provider's origin when
  configured, because browsers apply `form-action` to the redirect after the
  sign-in form); `frame-ancestors`, `base-uri`, `object-src` `'none'`.
- No inline script, inline style, `style` attribute or event handler attribute
  in templates. Data for scripts goes in `type="application/json"` blocks, as
  allauth does. htmx runs with `allowEval`, `allowScriptTags` and
  `includeIndicatorStyles` off and `selfRequestsOnly` on.
- drf-spectacular's Swagger page is replaced by
  `templates/api/swagger_ui.html`, which uses the split view (init script
  served by the same view) and a stylesheet instead of an inline style block.

## Consequences

- Tests fail on an inline script or style in the main pages, on an external URL
  in templates or static files, and on a changed htmx file.
- Some allauth pages not designed yet (email change) carry a `style` attribute,
  which the policy blocks; they will be overridden with the accounts lot.
