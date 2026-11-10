# API tokens

The tokens that let another tool, such as Home Assistant, use HouseCairn for you, at
`/me/tokens/` (**More**, then **API tokens**, next to
[Security and sign-in](security-and-sign-in.md)). A token acts as you, in the homes you
choose and with the rights you give it. The same operations are in the
[API](../api/index.md): `GET` and `POST /api/v1/me/tokens/`, `DELETE /api/v1/me/tokens/<id>/`.

**The list** shows your tokens that are not revoked: name and first characters, rights, homes,
creation date, last use and expiry. The value is never shown. An expired token stays in the
list, marked **Expired on**, so that you can revoke it and see why a tool stopped working.
On a phone, each token is a card.

**Create a token** opens the form:

- **Name**: what it is for, for example Home Assistant.
- **What it may do**: **Read** (ticked by default), **Write** and **Post events**. They do not
  include each other: a tool that reads and marks tasks done needs **Read** and **Write**.
  A token never does more than you: in each home it keeps at most your role.
- **Homes**: the homes it opens, and no other. A home that requires a sign-in provider is not
  offered: a token is not a sign-in through a provider and could not open it. When you have
  one home, it is ticked.
- **Expires after**: 30 days, **90 days** (the default, the lifetime set for the instance) or
  1 year. There is no token without an expiry: a forgotten token is a standing key, and
  creating a new one takes a minute.

**The value is shown once.** After **Create the token**, the page shows the value (it starts
with `hc_`) and a **Copy** button (when the browser can copy; otherwise select the field).
HouseCairn keeps only a digest of it: nobody, administrators included, can read it again.
If you lose it, revoke the token and create another. Reloading the page or tapping twice
creates nothing more, and the value is never shown again. Going back with the browser's back
button gives a new form, though, and sending it creates another token: check the list and
revoke the one you do not need.

**Revoke** opens a confirmation page. The tool that uses the token loses its access with its
next request. Revoking cannot be undone.

**What a token cannot do.** It cannot list, create nor revoke tokens: these are for a person
signed in. It also cannot change your account, your display preferences or your notification
channels (see the [API](../api/index.md)).

**Audit log.** Creating and revoking a token are noted in the audit log of the instance, with
the name of the token and who did it, never its value.
