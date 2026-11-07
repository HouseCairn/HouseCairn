"""allauth form overrides (docs/adr/0018)."""

from typing import Any

from allauth.account.forms import LoginForm as AllauthLoginForm
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

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


class DeleteAccountForm(forms.Form):
    """Confirmation of the erasure of an account: the address, and the password if there is one."""

    confirm_email = forms.EmailField(label=_("Type your email address to confirm"))
    password = forms.CharField(
        label=_("Your password"),
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, *args: Any, user: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        if not user.has_usable_password():
            # An account that signs in through a provider has no password to ask for.
            del self.fields["password"]

    def clean(self) -> dict[str, Any]:
        data: dict[str, Any] = super().clean() or {}
        email = data.get("confirm_email")
        if email and not services.same_address(email, self.user.email):
            self.add_error("confirm_email", _("This is not the address of your account."))
        if "password" in self.fields and not self.user.check_password(data.get("password") or ""):
            self.add_error("password", _("The password is not correct."))
        return data
