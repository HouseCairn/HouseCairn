# 0059. Notifications refuse private networks unless allowed, and `connect` checks its address

- Status: accepted
- Date: 2026-11-11
- Amends: [0043](0043-notifications-through-apprise.md) (*Private networks are allowed* and
  *Outgoing calls*)

## Context

ADR 0043 allowed private networks to every channel, as a risk accepted: the services people
host next to HouseCairn are on the local network. An external audit (2026-11-11) pointed out
what that costs on an instance with several accounts: any person who may add a channel can
make the server call an address of the local network, with the requests of the ntfy,
Gotify, Signal, Matrix, Mattermost, Apprise API or email plugins, and learn from the test
whether it answered. The same audit found that the guard of `socket.connect` did not check
the address, contrary to its docstring: the protection relied on every plugin resolving its
name through `socket.getaddrinfo` first. The maintainer decided on 2026-11-11 that private
addresses are refused by default and that an administrator may allow them.

## Decision

- **One rule, one more case.** `notifications.outbound.refused` stays the only rule of an
  address of a channel, on top of `core.netguard.forbidden_address` and the metadata
  services of cloud providers, which stay refused in every case. Unless private networks
  are allowed, every address that is not global (`core.netguard.is_public`: private
  networks, the shared address space `100.64.0.0/10`, unique local IPv6 addresses, the
  ranges of the documentation...) is refused too; an IPv6 address that carries an IPv4 one
  is judged by it, as before. `refusal` gives the reason: `address` (always refused) or
  `private` (refused by this rule only). No second list, no second mechanism.
- **A setting of the instance**, `notifications_private_networks`
  (`HOUSECAIRN_NOTIFICATIONS_PRIVATE_NETWORKS`, off), in the section *Notifications* of the
  settings screen, so only an instance administrator changes it (ADR 0035). It is read
  once per check of an address typed and once per send, in the thread that sends, before
  the guard starts; the threads of Apprise only read the guard.
- **Where it applies.** An IP address typed in the URL is judged when the channel is added;
  a name is judged when a message is sent, for the test as for a reminder, by the guard of
  `getaddrinfo`; the address of each connection is judged by the guard of `connect` (below).
  A channel added while private networks were allowed is not sent to once they are not.
- **What the person sees.** Adding a channel with a private address is refused with a
  sentence that says the address is on a private network and that an administrator of the
  instance can allow it, naming the setting. A test whose address leads to a private
  network answers the same sentence (a `ValidationError`, a 400 in the API) instead of
  "could not be sent": nothing was sent, and the person can do something about it. That
  tells a person who may already add a channel one more bit, whether a name resolves to a
  private address, which the decision accepts; the address itself is never shown. A
  reminder refused that way is not sent, and a warning is logged without the address.
- **`connect` checks its address.** While a message is sent, `socket.socket.connect` and
  `connect_ex` judge the address they are given with the same rule, IPv4, IPv6 and IPv4 in
  IPv6, scope removed, so a plugin that skipped `getaddrinfo` reaches nothing either. The
  plugins resolve first, then connect to an address; a name given to `connect` would be
  resolved by the C library, out of sight of the guard, so it is refused, and so is a
  socket that is neither IPv4 nor IPv6. Outside a send nothing changes.

## Consequences

- An instance whose people send to a ntfy or a Gotify of the local network turns the
  setting on after the update; until then those channels fail, and their test says why
  (an upgrade note says so).
- The setting on brings back the risk ADR 0043 accepted, with the same bounds, and the
  [hardening](../administration/hardening.md) page says so.
- What stays outside is what ADR 0043 lists, less the case of a plugin that would connect
  without resolving. A proxy set in the environment of the process is still what is
  called, but its address is now judged like any other: a proxy on a private network needs
  the setting on.
