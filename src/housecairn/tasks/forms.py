"""Forms of the task screens. Validation only; rules live in `services`."""

from typing import Any

from django import forms
from django.utils.dates import MONTHS
from django.utils.translation import gettext_lazy as _

from housecairn.rooms.models import Item
from housecairn.tasks import files, services
from housecairn.tasks.models import Occurrence, Task

_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Several files from one chooser; each is checked by the service, by its content."""

    widget = MultipleFileInput

    def clean(self, data: Any, initial: Any = None) -> Any:
        clean_one = super().clean
        if isinstance(data, list | tuple):
            return [clean_one(entry, initial) for entry in data if entry]
        return [clean_one(data, initial)] if data else []


class ItemChoiceField(forms.ModelChoiceField[Item]):
    """An item, shown with its room: two items can have the same name."""

    def label_from_instance(self, obj: Item) -> str:
        return f"{obj.room.name} · {obj.name}"


class TaskForm(forms.ModelForm[Task]):
    """A task: the title is the only required field; the rest is under the headings."""

    item = ItemChoiceField(label=_("Item"), queryset=Item.objects.none(), required=False)

    due_on = forms.DateField(label=_("Due on"), required=False, widget=_DATE)
    season_start_month = forms.TypedChoiceField(
        label=_("Season starts in"),
        required=False,
        choices=[("", _("No season")), *MONTHS.items()],
        coerce=int,
        empty_value=None,
    )
    season_end_month = forms.TypedChoiceField(
        label=_("Season ends in"),
        required=False,
        choices=[("", "—"), *MONTHS.items()],
        coerce=int,
        empty_value=None,
    )
    new_contractor = forms.CharField(label=_("Or a new contractor"), max_length=120, required=False)
    new_contractor_trade = forms.CharField(
        label=_("Trade of the new contractor"), max_length=120, required=False
    )
    uploads = MultipleFileField(
        label=_("Photos and files"),
        required=False,
        widget=MultipleFileInput(attrs={"accept": files.ACCEPT_ATTRIBUTE}),
    )

    field_order = [
        "title",
        "room",
        "item",
        "due_on",
        "priority",
        "repeat_mode",
        "repeat_interval",
        "repeat_unit",
        "season_start_month",
        "season_end_month",
        "hide_days_before",
        "assignee",
        "contractor",
        "new_contractor",
        "new_contractor_trade",
        "estimated_minutes",
        "labour_budget",
        "material_budget",
        "procedure",
        "notes",
        "uploads",
    ]

    class Meta:
        model = Task
        fields = [
            "title",
            "room",
            "item",
            "priority",
            "repeat_mode",
            "repeat_interval",
            "repeat_unit",
            "hide_days_before",
            "assignee",
            "contractor",
            "estimated_minutes",
            "labour_budget",
            "material_budget",
            "procedure",
            "notes",
        ]
        widgets = {
            "procedure": forms.Textarea(attrs={"rows": 8}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "procedure": _("Markdown: how to do it, step by step. Links to web pages only."),
        }

    def __init__(self, *args: Any, home: Any, with_files: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._choices("room").queryset = services.rooms_for_forms(home)
        self._choices("item").queryset = services.items_for_forms(home)
        self._choices("assignee").queryset = services.members_for_forms(home)
        self._choices("contractor").queryset = services.contractors_of(home)
        self.fields["contractor"].required = False
        for name in ("room", "item", "assignee", "contractor"):
            self.fields[name].empty_label = "—"  # type: ignore[attr-defined]
        if not with_files:
            del self.fields["uploads"]
        if self.instance.pk:
            current = services.open_occurrence_of(self.instance)
            self.initial.setdefault("due_on", current.due_on if current else None)

    def _choices(self, name: str) -> forms.ModelChoiceField[Any]:
        field = self.fields[name]
        assert isinstance(field, forms.ModelChoiceField)  # noqa: S101 - narrows the type
        return field

    def clean(self) -> dict[str, Any]:
        data: dict[str, Any] = super().clean() or {}
        if data.get("new_contractor") and data.get("contractor"):
            self.add_error("new_contractor", _("Choose a contractor or give a new one, not both."))
        return data


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
