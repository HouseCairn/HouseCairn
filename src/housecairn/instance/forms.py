"""Forms of the instance screens. Validation only; rules live in `services`."""

from django import forms
from django.utils.translation import gettext_lazy as _


class InstanceInviteForm(forms.Form):
    email = forms.EmailField(label=_("Email address"), max_length=254)
