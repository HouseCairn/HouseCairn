"""The form of a new API token."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from housecairn.accounts.models import User
from housecairn.apitokens import services
from housecairn.apitokens.models import Scope
from housecairn.homes.models import Home


class HomeChoiceField(forms.ModelMultipleChoiceField[Home]):
    def label_from_instance(self, obj: Home) -> str:
        return obj.name


def _lifetime_label(days: int) -> Any:
    if days % 365 == 0:
        return ngettext_lazy("%(n)d year", "%(n)d years", days // 365) % {"n": days // 365}
    return ngettext_lazy("%(n)d day", "%(n)d days", days) % {"n": days}


class TokenForm(forms.Form):
    name = forms.CharField(
        label=_("Name"),
        max_length=100,
        help_text=_("What the token is for, for example Home Assistant."),
    )
    scopes = forms.MultipleChoiceField(
        label=_("What it may do"),
        choices=[
            (Scope.READ.value, _("Read: see the homes, tasks and stock")),
            (Scope.WRITE.value, _("Write: change them, mark a task done")),
            (Scope.EVENTS.value, _("Post events: receive events from another tool")),
        ],
        initial=[Scope.READ.value],
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Write does not include read: tick both for an integration that does both."),
    )
    homes = HomeChoiceField(
        label=_("Homes"),
        queryset=Home.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        help_text=_("The token opens these homes and no other."),
    )
    lifetime_days = forms.TypedChoiceField(
        label=_("Expires after"),
        coerce=int,
        choices=[(days, _lifetime_label(days)) for days in services.LIFETIME_CHOICES],
        widget=forms.RadioSelect,
        help_text=_("There is no token without an expiry: you create a new one before it ends."),
    )

    def __init__(self, *args: Any, user: User, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        homes = services.issuable_homes(user)
        self.fields["homes"].queryset = homes  # type: ignore[attr-defined]
        if not self.is_bound and homes.count() == 1:
            self.fields["homes"].initial = list(homes)
        self.fields["lifetime_days"].initial = services.default_lifetime_days()

    def clean_name(self) -> str:
        return " ".join(self.cleaned_data["name"].split())
