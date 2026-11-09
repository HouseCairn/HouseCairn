"""The contractor form."""

from typing import Any

from django import forms

from housecairn.tasks.models import (
    Contractor,
    Trade,
)


class ContractorForm(forms.ModelForm[Contractor]):
    """A contractor: only the name is required (docs/adr/0045)."""

    class Meta:
        model = Contractor
        fields = ["name", "trade", "trade_other", "phone", "email", "address", "note"]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 3}),
            "phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "off"}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        trade = self.fields["trade"]
        assert isinstance(trade, forms.ChoiceField)  # noqa: S101 - narrows the type
        trade.choices = [("", "—"), *Trade.choices]
        self.fields["trade"].required = False
