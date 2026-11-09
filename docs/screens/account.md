# Account pages

The other pages under `/accounts/` manage your account: sign-up when it is
open, sign-out, password change and reset, email addresses (when the instance
sends email), two-factor
authentication (authenticator app, recovery codes, passkeys) and the
identities linked through single sign-on. They come from django-allauth and
use the layout of the application. They are listed on the
[Security and sign-in](security-and-sign-in.md) page, in the **Me** group of
[More](more.md). How passkeys are used to sign
in is on the [Sign-in](sign-in.md) page.

## Security emails

When the instance sends email, you receive a message when your password is
changed or set, when an address is added, changed or removed, when a passkey or
the authenticator app is added or removed, and when you sign in from a browser
the account had not seen (with its address and browser). If you do not
recognise the change, change your password and review your passkeys.

## Delete my account

**Delete my account**, at the bottom of the
[Security and sign-in](security-and-sign-in.md) page, erases your account for
good: your sign-in methods, your API tokens, the homes where you are the only
member, and the invitations to your address. Homes you share with others stay
with them. Type your address, and your password if you have one.

- If you are the only owner of a home with other members, the page lists it:
  hand ownership over, or delete the home, first.
- The only administrator of the instance cannot delete the account.
