# 0003. Web/API parity, checked by a test

- Status: accepted
- Date: 2026-11-07

## Context

Principle P8: no function exists only in the web interface. The iOS app and
the integrations must be able to do everything a person can do in a browser.
A rule that is only written down is forgotten.

## Decision

`src/housecairn/parity.py` holds a registry:

- `PARITY` maps each named web route to the API route(s) offering the same
  function, for example `homes:detail` to `api-v1:home-detail`;
- `EXEMPT` lists web routes without business function (landing page, health
  probe, API documentation), each with its reason;
- allauth and the Django admin are exempt as a whole: account management is
  not exposed to API tokens, and the admin is an operator tool.

`tests/test_parity.py` walks the URL configuration and fails if a named web
route is neither mapped nor exempted, or if a mapped API route does not exist.

## Consequences

- Adding a web screen without its API endpoint fails the test suite.
- The registry is reviewed with every pull request that adds a route.
- Parity is checked at route level; that the API does the same thing is the
  job of the service layer (0002), which both call.
