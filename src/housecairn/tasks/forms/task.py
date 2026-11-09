"""The task form. Validation only; rules live in `services`."""

from typing import Any

from django import forms
from django.utils.dates import MONTHS
from django.utils.translation import gettext_lazy as _

from housecairn.accounts.models import User
from housecairn.rooms.models import Item
from housecairn.tasks import durations, files, services
from housecairn.tasks.forms.fields import (
    _DATE,
    ItemChoiceField,
    MultipleFileField,
    MultipleFileInput,
    PersonChoiceField,
)
from housecairn.tasks.models import (
    Season,
    Task,
)


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
