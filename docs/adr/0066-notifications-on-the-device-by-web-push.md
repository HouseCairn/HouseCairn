# 0066. Notifications on the device by Web Push, on `cryptography` alone

- Status: accepted
- Date: 2026-11-12
- Amends: [0043](0043-notifications-through-apprise.md) (a second way to reach a person),
  [0065](0065-installable-application-and-offline-reading.md) (the service worker shows
  notifications)

## Context

The maintainer decided on 2026-11-11 that a person should receive reminders on their phone
without installing anything else, ntfy included: a notification channel "this device" by
Web Push, which Android, computers and iOS 16.4 or later (once the application is
installed) support. Web Push needs two things on the server: the encryption of each message
for the browser (RFC 8291, with the `aes128gcm` content coding of RFC 8188) and a signature
that names the server to the push service (VAPID, RFC 8292). The messages go through the
push service the browser chose, which the instance does not choose: Google (Firebase Cloud
Messaging), Mozilla, Apple or Microsoft, some outside the EU.

## Decision

- **No new dependency.** `cryptography` is already a direct one (ADR 0035) and has every
  primitive: P-256 ECDH, HKDF from HMAC-SHA-256, AES-128-GCM, ECDSA with SHA-256.
  `notifications.webpush` implements the encryption and the signature in about 200 lines,
  tested against the example of RFC 8291 (its section 5 and the intermediate values of its
  Appendix A). `pywebpush` would have brought `http-ece`, `py-vapid` and `requests` calls
  outside the guard of the instance.
- **Off by default**, in two settings of the section *Notifications* (ADR 0035):
  `webpush_enabled` (`HOUSECAIRN_WEBPUSH_ENABLED`, off), on top of `notifications_enabled`,
  and `webpush_discreet` (`HOUSECAIRN_WEBPUSH_DISCREET`, **on**): a notification then says
  only what kind of message it is ("A task is due.", "Tasks are due.", "A problem was
  reported.") and opens the screen, so that nothing of a home shows on a locked screen.
  Off, it holds the same text as a channel (title of the task, home, due date).
- **What leaves the instance.** A JSON message, encrypted for the device: a title, a line
  of text and the path of the screen to open, at most what a push service must accept
  (4096 octets, the text cut when needed). The push service sees the endpoint, the time,
  the size and the public key of the instance, never the text. Time to live: one day.
- **The key pair of the instance** (`PushKey`, one row) is made at first use. Its private
  key is sealed by `instance.crypto` like every stored secret, so a backup without the
  secret key does not give it (ADR 0060). If it cannot be read, a new pair is made and every
  device is removed, since each was subscribed with the old public key.
  `manage.py rotate_push_key` does the same on purpose. The VAPID subject is the public
  address of the instance when it is HTTPS, a placeholder `mailto:` otherwise.
- **A device belongs to one person** (`Device`): a name, the name of its push service,
  and its endpoint and two keys, sealed and never shown, exported or logged; the account
  export lists the name and the service only, and the export of a home has no device. One
  device per endpoint: the same browser subscribing again replaces its keys, and a browser
  another account had subscribed belongs to the new one only. Five devices a person, so that a run of reminders still ends within the timeout of the
  worker. A push
  service that answers 404 or 410 has forgotten the device: it is removed.
- **Which endpoints.** HTTPS, port 443, no user name nor password, and a host that is, or
  ends with, `fcm.googleapis.com`, `push.services.mozilla.com`, `push.apple.com` or
  `notify.windows.com`: any other host, and any IP address, is refused when the device is
  added and again when a message is sent. The post itself goes through
  `core.netguard.post`: every address of the name must be public (`is_public`), the
  connection goes to an address that passed, no redirect is followed, eight seconds in all.
  The setting of private networks (ADR 0059) does not apply: no push service is on one.
- **Who sends.** The background worker: the reminders and the summaries (`reminders`) and
  the alert of a report (`alerts`) go to the devices of the person as to their channels;
  a person with a device and no channel is reachable. The test of a device is queued for
  the worker too.
- **Where.** Adding a device is a script (`static/js/webpush.js`): the browser asks for its
  permission on the click of **Receive on this device** only, then the subscription goes to
  `POST /api/v1/me/push-devices/` with the session. Renaming, testing and removing are
  forms of the web, and the same API. An API token reads the list with `write`, like the
  channels, and changes nothing (`PersonOnlyToChange`): a test walks every route of
  `me/` of the API and checks that no token writes there.
- **The service worker** shows the notification (`push`) and opens its path on a click
  (`notificationclick`), only under its own scope: a path of another origin, or outside the
  prefix of the instance, opens the start address.

## Consequences

- An instance that turns it on sends to services of Google, Mozilla, Apple or Microsoft,
  chosen by each browser; the [hardening](../administration/hardening.md) page says so.
- Signing out does not stop the notifications of a browser; the guide says to stop them
  first on a shared computer.
- What no test of the repository does: subscribing a real browser to a real push service
  and seeing the notification on a phone, an iPhone with the application installed above
  all. That is checked by hand.
