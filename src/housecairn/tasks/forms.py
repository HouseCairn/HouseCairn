"""Forms of the task screens. Validation only; rules live in `services`."""

from typing import Any

from django import forms
from django.conf import settings
from django.utils.dates import MONTHS
from django.utils.translation import gettext_lazy as _

from housecairn.accounts.models import User
from housecairn.accounts.names import person_name
from housecairn.rooms.models import Item
from housecairn.tasks import durations, files, services
from housecairn.tasks.models import (
    Contractor,
    DisplayPreference,
    Occurrence,
    Season,
    Task,
    Trade,
)

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


class PersonChoiceField(forms.ModelChoiceField[User]):
    """A member of the home, by their name and never by their address (docs/adr/0045)."""

    def label_from_instance(self, obj: User) -> str:
        return person_name(obj)


class TaskForm(forms.ModelForm[Task]):
    """A task: the title is the only required field; the rest is under the headings."""

    assignee = PersonChoiceField(label=_("Assignee"), queryset=User.objects.none(), required=False)
    item = ItemChoiceField(label=_("Item"), queryset=Item.objects.none(), required=False)

    due_on = forms.DateField(label=_("Due on"), required=False, widget=_DATE)
    season = forms.ChoiceField(
        label=_("Season"),
        required=False,
        choices=[("", _("All year")), *Season.choices],
    )
    season_start_month = forms.TypedChoiceField(
        label=_("Custom season starts in"),
        required=False,
        choices=[("", "—"), *MONTHS.items()],
        coerce=int,
        empty_value=None,
    )
    season_end_month = forms.TypedChoiceField(
        label=_("Custom season ends in"),
        required=False,
        choices=[("", "—"), *MONTHS.items()],
        coerce=int,
        empty_value=None,
        help_text=_("Only used with the season Custom months."),
    )
    duration_value = forms.IntegerField(
        label=_("Estimated duration"), required=False, min_value=1, max_value=durations.MAX_MINUTES
    )
    duration_unit = forms.ChoiceField(
        label=_("Unit"), choices=durations.UNIT_CHOICES, initial=durations.HOUR, required=False
    )
    contractor_name = forms.CharField(
        label=_("Contractor"),
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"list": "contractor-options", "autocomplete": "off"}),
        help_text=_(
            "Pick one from the suggestions or type a new name: it joins the contractors of "
            "the home when you save."
        ),
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
        "season",
        "season_start_month",
        "season_end_month",
        "hide_days_before",
        "assignee",
        "contractor_name",
        "duration_value",
        "duration_unit",
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
            "labour_budget",
            "material_budget",
            "procedure",
            "notes",
        ]
        widgets = {
            "procedure": forms.Textarea(attrs={"rows": 8}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"room": _("Room")}
        help_texts = {
            "procedure": _("Markdown: how to do it, step by step. Links to web pages only."),
        }

    def __init__(self, *args: Any, home: Any, with_files: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._choices("room").queryset = services.rooms_for_forms(home)
        self._choices("item").queryset = services.items_for_forms(home)
        self._choices("assignee").queryset = services.members_for_forms(home)
        self.contractors = list(services.contractors_of(home))
        hemisphere = home.get_hemisphere_display().lower()
        self.fields["season"].help_text = _(
            "The season follows the hemisphere of the home (%(hemisphere)s): change it in the "
            "settings of the home."
        ) % {"hemisphere": hemisphere}
        for name in ("room", "item", "assignee"):
            self.fields[name].empty_label = "—"  # type: ignore[attr-defined]
        if not with_files:
            del self.fields["uploads"]
        if self.instance.pk:
            current = services.open_occurrence_of(self.instance)
            self.initial.setdefault("due_on", current.due_on if current else None)
            if self.instance.contractor is not None:
                self.initial.setdefault("contractor_name", self.instance.contractor.name)
            if self.instance.estimated_minutes:
                value, unit = durations.split(self.instance.estimated_minutes)
                self.initial.setdefault("duration_value", value)
                self.initial.setdefault("duration_unit", unit)

    def _choices(self, name: str) -> forms.ModelChoiceField[Any]:
        field = self.fields[name]
        assert isinstance(field, forms.ModelChoiceField)  # noqa: S101 - narrows the type
        return field

    def clean(self) -> dict[str, Any]:
        data: dict[str, Any] = super().clean() or {}
        value, unit = data.pop("duration_value", None), data.pop("duration_unit", None)
        minutes = None
        if value is not None:
            minutes = durations.to_minutes(value, unit or durations.HOUR)
            if not durations.within_bounds(minutes):
                self.add_error(
                    "duration_value", _("Give a duration between a minute and thirty days.")
                )
        data["estimated_minutes"] = minutes
        if (
            not data.get("season")
            and data.get("season_start_month")
            and data.get("season_end_month")
        ):
            data["season"] = Season.CUSTOM  # months given without a season: a custom one
        if data.get("season") != Season.CUSTOM:
            # The months are the person's own only for a custom season.
            data["season_start_month"] = data["season_end_month"] = None
        elif data.get("season_start_month") is None or data.get("season_end_month") is None:
            self.add_error("season_start_month", _("Give the first and the last month."))
        return data


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


class PreferencesForm(forms.ModelForm[DisplayPreference]):
    """The Today screen, as one person wants it."""

    class Meta:
        model = DisplayPreference
        fields = [
            "today_group",
            "horizon_days",
            "show_overdue",
            "show_upcoming",
            "show_season",
            "language",
        ]
        widgets = {"today_group": forms.RadioSelect}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["language"] = forms.ChoiceField(
            label=_("Language"),
            required=False,
            choices=[("", _("Automatic (browser, then instance default)")), *settings.LANGUAGES],
            help_text=_("Applies to every page you open, on every device you sign in from."),
        )


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
