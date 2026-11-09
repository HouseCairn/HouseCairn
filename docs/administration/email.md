# Email

HouseCairn sends email for invitations, address verification, password reset
and security alerts. It is off until `EMAIL_HOST` is set.

| Variable | Default | Purpose |
| --- | --- | --- |
| `EMAIL_HOST` | (none) | SMTP server. Empty: email is off. |
| `EMAIL_PORT` | `587` | Port of the server. |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | (none) | Credentials, if the server asks for them. |
| `EMAIL_USE_TLS` | `true` | STARTTLS on the connection (port 587). |
| `EMAIL_USE_SSL` | `false` | TLS from the first byte (port 465). Replaces `EMAIL_USE_TLS`. |
| `EMAIL_TIMEOUT` | `15` | Seconds to wait for the server: a server that does not answer must not hold a web process. |
| `DEFAULT_FROM_EMAIL` | `HouseCairn <noreply@localhost>` | Sender; set it to an address of your domain. |
| `HOUSECAIRN_SITE_URL` | (none) | Public address, for the links in emails. **Set it in production.** |

Keep TLS on: sending credentials and messages in clear text is accepted by
nothing here and by few servers. With a server on port 465 set
`EMAIL_USE_SSL=true` and `EMAIL_PORT=465`.

## What is sent

Every message has a text and an HTML version, in the language of the person
who triggered it (English or French), signed HouseCairn, with a subject that
starts with `HouseCairn:`.

- **Invitations** to a home and to the instance.
- **Verification** of an address, and **password reset**.
- **Security alerts**: password changed or set, address added, changed or
  removed, passkey or authenticator app added or removed, recovery codes
  generated, and **a sign-in from a browser the account had not seen**. The
  last one relies on a cookie that holds a random secret per browser; the
  account keeps only its digest, for at most 20 browsers. The first browser of
  an account raises no alert.

## Without email

Without `EMAIL_HOST`, or with a console or dummy backend, nothing is delivered.
What depends on it is hidden or falls back: the *Forgot your password?* link
and its pages (404), the page of email addresses, invitations to the instance,
security alerts (not recorded
either), and open sign-up (refused at start-up). An invitation to a home shows
its link once to the owner, who passes it on; such a link cannot create an
account.

If the mail server fails, nothing breaks: an invitation stays saved and the
page says the email could not be sent, a sign-in goes through, and the failure is
logged without the address.

## Verifying an address by hand

An invitation to a home that the owner handed over by hand is accepted only by an account that
verified the invited address. Without outgoing email nobody can verify it: an account made by
`createsuperuser`, or signed up while verification was off, is stuck. The administrator of the
server verifies the address from the command line:

```
manage.py verify_email ivy@example.com
manage.py verify_email ivy@example.com --primary
```

The address is found whatever its case. With `--primary` it also becomes the primary address
of its account, so the sign-in address. The command fails, changing nothing, when no account has
the address, or when several do (it then lists their identifiers, never other addresses). Run
again, it changes nothing and says so. A change is recorded in the audit log of the instance.

Use it only for an address you know belongs to the person: it is the check the email would have
made.

## Links

Links point to `HOUSECAIRN_SITE_URL`, including those of password reset and
verification. Without it they take the `Host` of the request that triggered
them, which `ALLOWED_HOSTS` limits but a permissive proxy can bend:
`manage.py check --deploy` warns when `EMAIL_HOST` is set without it.
