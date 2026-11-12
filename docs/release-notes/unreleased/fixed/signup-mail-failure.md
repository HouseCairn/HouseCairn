---
orphan: true
nosearch: true
---

- **Sign-up no longer fails with a server error when the mail server does not answer.** With
  sign-up open, a mail server that was unreachable, slow, or that refused the credentials or
  the message made the sign-up page fail with a server error, after the account had been
  created without its verification message. The sign-up is now undone as a whole and the form
  comes back with a message that says the confirmation email could not be sent; the same
  address can try again at once. The other messages of the sign-in flows are covered the same
  way: a password reset, a sign-in with an unverified address, an added address and a new
  verification message answer with the reason instead of a server error, and the security
  notices (password or primary address changed) are sent on a best-effort basis, so that the
  change itself is never undone by a mail server that fails.
