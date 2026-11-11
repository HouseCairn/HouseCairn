# 0065. Installable application and offline reading

- Status: accepted
- Date: 2026-11-11
- Extends: [0055](0055-serving-under-a-path-prefix.md) (path prefix),
  [0011](0011-no-external-resources-and-csp.md) (Content Security Policy)

## Context

The application had a web app manifest and no service worker. The maintainer decided on
2026-11-11 that it becomes a full progressive web application: the browser offers to
install it, and Today and the task list of the current home can be read offline. Push
notifications are a later, separate change. Writing offline (a queue replayed once back
online) is out of scope: a household of several people would then need conflict rules.

## Decision

**Installation.** What each browser needs, checked against their documentation in
November 2026:

- Chrome and Edge (Android and computer): a manifest with `name` or `short_name`, icons of
  192 and 512 pixels, `start_url`, `display: standalone`, served over HTTPS (or
  `localhost`). A service worker is no longer required by Chrome, but it is there anyway.
- Firefox on Android: the same manifest; Firefox on a computer does not install web
  applications.
- Safari on iOS and iPadOS: no prompt; the person uses Share, then Add to Home Screen.
  Safari reads the manifest (`display`, `start_url`, `scope`) and, for the name and the
  icon, `apple-mobile-web-app-title` and `apple-touch-icon`.

The manifest gains `id` (the start address, so one installed application per instance
and prefix) and two `maskable` icons (`img/brand/icon-maskable-*.png`): the icon on a full
square of the slate colour, with no transparent corner, so Android launchers cut it to
their shape without a white frame. They were made once from `icon-192.png` and
`icon-512.png` with Pillow (the transparent corners filled with the slate colour); the
cairn already sits inside the central safe circle. `screenshots` are not added: no browser
requires them, and the project takes no screenshot before its dedicated lot (0017).

`<link rel="manifest">` carries `crossorigin="use-credentials"`. Browsers fetch the
manifest without cookies otherwise; behind an authentication proxy (a common setup when
self-hosting), the proxy then answers its own sign-in page instead of the manifest, and
the browser offers no installation.

**Service worker.** `service-worker.js` is a view at the root of the application, so its
scope is all of it: `/` at the root, the prefix under a prefix (`/housecairn/`), whether the
prefix is fixed or given by the proxy. It answers `Service-Worker-Allowed` with that scope,
`Cache-Control: no-cache` (the browser checks it at each visit) and its configuration in
JSON (scope, addresses, version). The CSP gains `worker-src 'self'`, which only states
what `script-src 'self'` already allowed. `static/js/offline.js`, on every page, registers
it; a browser without service worker (a private window that refuses storage) runs the
application as before.

**What is kept, for whom, and for how long.**

| Kept | For whom | How long |
| --- | --- | --- |
| Static files (styles, scripts, icons, fonts), the offline page | Anyone who uses the browser | Until the next version of the static files (a new cache named after their fingerprint, the old one deleted) |
| Today and the task list of the current home, as last opened online | The signed-in person, in this session, for this home | Until sign-out, a 401 or 403, a signed-out page, a new session, another person, or another current home |

- The server decides what a page may be kept: `core.offline.OfflinePagesMiddleware` adds
  `HouseCairn-Offline: <key>` only on Today (`tasks:today`) and the task list
  (`tasks:list`) of the current home, for a signed-in person, on a GET answered 200 in
  HTML and not `no-store`, and adds `Cache-Control: private`. No other page carries it:
  not the account and security screens, the API tokens, the calendar feeds, the
  administration, the exports, the forms. A test lists them.
- The key is an HMAC of the person, the session and the home, under the secret key. The
  service worker keeps the pages of one key only: keeping a page under a new key deletes
  the pages of any other. A new sign-in, another person on the same browser or another
  home therefore starts from nothing; nothing of another home is ever kept.
- The service worker keeps a page only from the network (network first), when the
  response is 200, of the same origin, not redirected, not `no-store`, and carries a key.
  It never keeps a write (anything but GET), an error page, nor a page without the header.
- It deletes every kept page when the person signs out (the POST to the sign-out address),
  on any response marked `HouseCairn-Offline: purge` (every HTML page of a signed-out
  visitor, such as the sign-in page a lapsed session is sent to; every 401 and 403), and
  when a signed-out page tells it so. Only HTML pages carry `purge`: a manifest fetched
  without the cookie must not empty the cache.
- The offline page is rendered without the request: no navigation, no home name, no form
  token. It is the answer to any page not kept, offline.
- The cache names start with `housecairn:<scope>:`: two instances under two prefixes of
  one origin never read nor delete each other's caches. Clear-Site-Data was not used for
  the sign-out: under a prefix it would also empty the storage of the other applications
  of the origin.

**Offline, read only.** A kept page served from the cache is marked by the service worker;
`offline.js` then shows "Offline: data from <date and time>" (the time the server rendered
the page) and turns off every button that writes (forms posted, HTMX writes), described by
the banner. The same happens when the connection drops on a page already open; it comes
back with the connection. Nothing is queued.

## Consequences

- A shared computer: the pages of the last person stay readable offline until they sign out
  or someone else signs in; the session itself already allowed as much online.
- A person who opens the installed application for the first time must be online once:
  the pages are kept from the first navigation the service worker sees, the second visit.
- `tests/e2e/pwa_checks.py` (workflow UI, job "Installable app and offline") checks it in
  Chromium, at the root and under a prefix, with production settings and gunicorn. What no
  script checks, and is to be tried by hand on each release that touches it: the
  installation prompt of Chrome on Android, Add to Home Screen on an iPhone (name, icon,
  standalone window), the maskable icon on an Android launcher, and the installation behind
  an authentication proxy.
