"""allauth form overrides (docs/adr/0018)."""

from typing import Any

from allauth.account.forms import LoginForm as AllauthLoginForm
from django.conf import settings

from housecairn.accounts import services


class LoginForm(AllauthLoginForm):  # type: ignore[misc]
    """Sign-in form whose address field also offers the browser's passkeys.

    The `webauthn` autofill token (and nothing else) is what lets a browser list
    the passkeys saved for this site in the address field's suggestion list; the
    script `js/passkey-login.js` completes the request.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if settings.MFA_PASSKEY_LOGIN_ENABLED:
            self.fields["login"].widget.attrs["autocomplete"] = "username webauthn"
        if not services.email_is_configured():
            # allauth links "Forgot your password?" under the field; the reset
            # mail could not be sent, so the link would lead nowhere useful.
            self.fields["password"].help_text = ""
