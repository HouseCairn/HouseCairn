# 0043. Notifications through Apprise: channels of a person, reminders, quiet hours

- Status: accepted
- Date: 2026-11-08

## Context

A task is only useful if someone remembers it. People already have a place where they read
alerts (ntfy, Telegram, Signal, Matrix, Gotify, email), and the project does not write
clients for each service (rule: integrate, do not reinvent). Apprise speaks to more than a
hundred services through one URL per service. That URL carries the service's secrets (a bot
token, a password), and it makes the server call an address that a person typed.

## Decision

**A new app, `notifications`**, with three tables, all owned by one person: `Channel` (a
name, the sealed Apprise URL, its scheme and service name, on or off), `Preference`
(first reminder, time of day, quiet hours, daily summary, language, time zone) and
`Delivery` (one row per message claimed). No home owns a channel. No file of another app
changed, apart from one-line hooks (navigation, URLs, settings, the registry of settings).
One new runtime dependency, `apprise`, is added to the list of ADR 0001.

**The address is a secret.** It is encrypted with `instance.crypto`, the key derived from
`SECRET_KEY` (ADR 0035), and decrypted only in `notifications.outbound`, at the moment of
sending. It is write-only: the form field is a password field that is never rendered back,
the API field is `write_only`, and the address cannot be changed (delete and add again).
What is shown of a channel is its name, its scheme and the name of the service, never a
host: the host of a Telegram URL is part of its bot token. The export lists channels
without their address. The audit log records nothing about channels. Apprise and urllib3
write log lines that carry URLs, so their loggers are silenced; an error is logged by the
class of the exception only.

**A list of allowed schemes.** Only services reached over HTTP(S) or SMTP whose plugin
fixes the method, the path and the format of every request are accepted. For each one,
what the person who types the URL chooses, and what the plugin fixes:

| Schemes | Host | Requests (fixed by the plugin) | Chosen by the person |
| --- | --- | --- | --- |
| `ntfy(s)` | any | `POST /` with the JSON of ntfy | host, port, topic (a field of the body) |
| `gotify(s)` | any | `POST <prefix>/message` with the JSON of Gotify | host, path prefix, token |
| `signal(s)` | any | `POST <prefix>/v2/send` (signal-cli REST API) | host, prefix, numbers |
| `matrix(s)` | any | Matrix client API (`POST` login and join, `PUT` the message), or with `mode=` a `POST` of the JSON of a webhook bridge | host, account, rooms; the webhook path |
| `mmost(s)` | any | `POST <prefix>/hooks/<token>` with the JSON of Mattermost | host, prefix, token |
| `apprise(s)` | any | `POST <prefix>/notify/<token>` (Apprise API) | host, prefix, token |
| `mailto(s)` | any | SMTP: one message, fixed headers | server, account, recipients |
| `tgram`, `discord`, `slack`, `pover` | fixed (the public API) | `POST` to the API of the service | the tokens of the person's own account |

No URL option sets the method, adds a header or adds a field: Apprise reads
`+name=value` as an extra header, `-name` and `:name=value` as a field removed from or
added to the body, so a URL with any of them is refused. The generic webhooks `json(s)`,
`xml(s)` and `form(s)` are not offered: their URL chooses the method (`?method=DELETE`),
the path, the headers and the fields, which would let any account send almost any HTTP
request to the local network. A plugin that runs something on the server (`dbus`,
`windows`, `macosx`), writes to a local log (`syslog`), opens a raw socket (`rsyslog`,
`mqtt` and the like) or reads a file is not offered either. A URL whose options make a
plugin read a local file (a `template=`, a PGP key) is refused. The test checks that the
scheme parsed by Apprise is the one in the list, so an alias cannot bring another plugin.
The list is checked again each time a message is sent: a channel saved under a scheme
removed since is not called.

**Outgoing calls.** Apprise has no hook for the connections of its plugins: each one calls
`requests` or `smtplib` itself. What the instance controls, and how:

- *Names.* While a message is sent, a guard (a context variable, so it follows the thread
  of the send) wraps `socket.getaddrinfo`. Every address a name resolves to is checked, and
  the connection is made to an address of that same answer: there is no second resolution,
  hence no DNS rebinding between the check and the call. Outside a send, resolution is left
  as it was.
- *Addresses.* The same rule as the test of an identity provider (ADR 0041): loopback,
  link-local (cloud metadata services), multicast, unspecified and reserved addresses are
  refused, an IPv6 address that carries an IPv4 one is judged by that IPv4 address, and an
  address typed as is in the URL is refused when the channel is added.
- *Redirects.* `requests` follows none while a message is sent: the 3xx answer counts as a
  failure.
- *Certificates* are verified; every connection waits five seconds at most.
- *What the person sees.* The test button sends a real message and answers one of two
  fixed sentences, sent or not sent, never the service's answer or error. Five tests a
  minute per person.

What stays outside: a plugin that would resolve a name some other way than `getaddrinfo`,
or a proxy set in the environment of the process (then the proxy is what is called). The
list of schemes keeps the plugins to ones that use `requests` or `smtplib`.

**Private networks are allowed**, as in ADR 0041, and for the same reason: the services
people self-host next to HouseCairn (ntfy, Gotify, a signal-cli bridge, a mail relay) run on
the local network, and refusing it would refuse the main case. The cost is that a person
with an account can make the instance call a private address, with the requests of one of
the plugins above, and learn whether it answered with success. That is bounded:
notifications are off until an administrator turns them on, a test is a fixed message
whose method, path suffix, headers and format are those of the plugin, its answer is one
bit, and tests are limited. An administrator who does not want it leaves notifications off.

**Messages.** A reminder says the title of the task, the home, the due date and a link to
the task (when the public address is set): no note, procedure, cost or file leaves the
instance. It is in the language of the person. The text is sent as plain text: Apprise
escapes it for the format of each channel (HTML or Markdown, as the service expects), so a
title cannot change the markup of the message. The title of a message is fixed.

**Who is reminded.** The person in charge of the task, if they may still write in the
home; otherwise every member of the home who may write and has a channel on. Readers are
never reminded, nor anyone outside the home.

**When.** The first reminder goes out `days_before` days before the due date (1 by
default, 0 to 30), from `send_at` (08:00 by default) in the time zone of the person, or
of the instance. Follow-ups come every day for a high priority, every three days for a
normal one and every week for a low one, while the occurrence is open. Done and skipped
close it, so the reminders stop. Postponing moves the due date: the reminders start again
from the new date. During the quiet hours of a person, which may run past midnight,
nothing is sent; what was due is sent at the first run after them. With the daily summary
on, one message a day groups every task to remind, from `send_at`.

**Once only.** Each message has a key: the occurrence, its due date and the number of the
follow-up, or the day of a summary. It is claimed by inserting a `Delivery` row before
anything is sent; a unique constraint on (person, kind, key) lets one worker only send it,
even when two runs cross. A message claimed and not delivered (the service failed, the
worker stopped) is not tried again: the next follow-up is. Rows older than 90 days are
removed.

**In the background.** `notifications.tasks.dispatch` runs in the django-q2 worker already
in the container (ADR 0008), from a `Schedule` created after `migrate` and kept at the
interval of the settings by each run, so a change applies without a restart. No new
process and no separate decision record.

**Settings** (ADR 0035): `notifications_enabled` (`HOUSECAIRN_NOTIFICATIONS_ENABLED`, off
by default) and `notifications_interval` (`HOUSECAIRN_NOTIFICATIONS_INTERVAL`, 5 minutes,
1 to 60), in a section *Notifications* of the settings screen. They are declared in
`notifications.conf` and added to the registry by one line at its end. Off, nothing is
sent and no channel can be added or tested; existing channels stay.

**Isolation.** Channels are looked up among those of the person signed in: someone else's,
an instance administrator's included, is the same 404 as a channel that does not exist.
The Django administration site has no notification model. Through the API, an API token
needs the `write` scope for every endpoint of notifications, reading included: a channel
makes the server send messages, which a `read` token must not allow; an `events` token
reaches nothing. Deleting an account deletes its channels, preferences and deliveries.

## Consequences

- Any service Apprise supports over HTTP(S) or SMTP can be added to the list later, after
  checking how its plugin connects.
- Home Assistant as a channel (a webhook the instance calls, J3), web push and stock alerts
  are outside this record.
- A failed reminder is not retried; the next follow-up is the retry.
