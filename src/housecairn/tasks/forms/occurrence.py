"""Forms of an occurrence: completion, postponement, attachments."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from housecairn.tasks import files
from housecairn.tasks.forms.fields import (
    _DATE,
    MultipleFileField,
    MultipleFileInput,
)
from housecairn.tasks.models import (
    Occurrence,
)


class CompletionForm(forms.ModelForm[Occurrence]):
    """The details of a task that is done: when, what it cost, a note."""

    class Meta:
        model = Occurrence
        fields = ["completed_on", "actual_cost", "completion_note"]
        widgets = {
            "completed_on": _DATE,
            "completion_note": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"completion_note": _("Note")}


class PostponeForm(forms.Form):
    due_on = forms.DateField(label=_("New date"), widget=_DATE)


class AttachmentForm(forms.Form):
    uploads = MultipleFileField(
        label=_("Photos and files"),
        widget=MultipleFileInput(attrs={"accept": files.ACCEPT_ATTRIBUTE}),
    )

    def clean(self) -> dict[str, Any]:
        data: dict[str, Any] = super().clean() or {}
        if not data.get("uploads") and "uploads" not in self.errors:
            self.add_error("uploads", _("Choose at least one file."))
        return data
