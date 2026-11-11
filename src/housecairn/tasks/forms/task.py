"""The task form. Validation only; rules live in `services`."""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.dates import MONTHS
from django.utils.translation import gettext_lazy as _

from housecairn.accounts.models import User
from housecairn.core.forms import MoneyField
from housecairn.rooms.models import Item
from housecairn.tasks import durations, files, recurrence, repeat_text, services
from housecairn.tasks.forms.fields import (
    _DATE,
    ItemChoiceField,
    MultipleFileField,
    MultipleFileInput,
    PersonChoiceField,
)
from housecairn.tasks.models import (
    RepeatMode,
    Season,
    Task,
)

# "Count from": the two ways a task repeats, said as the end of the sentence.
REPEAT_FROM_CHOICES = [
    (RepeatMode.FIXED.value, _("the due date")),
    (RepeatMode.AFTER_LAST.value, _("the day it is done")),
]


def _shown(form: forms.BaseForm, name: str) -> Any:
    """The value of a field as the page shows it (sent, else initial); None if invalid."""
    try:
        return form.fields[name].clean(form[name].value())
    except ValidationError:
        return None


def _changed(form: forms.BaseForm, name: str) -> bool:
    if not form.is_bound:
        return False
    bound = form[name]
    return form.fields[name].has_changed(bound.initial, bound.data)


def repeat_summary(form: forms.BaseForm, home: Any) -> str:
    """The sentence of the repetition, for the values of a task form (sent or initial).

    The date counted from is the due date, or the date of the repetition when only that
    one was changed, the rule `TaskForm` applies on save.
    """
    mode = RepeatMode.ONCE
    if _shown(form, "repeats"):
        mode = _shown(form, "repeat_from") or RepeatMode.AFTER_LAST
    start = _shown(form, "due_on")
    if _changed(form, "repeat_start") and not _changed(form, "due_on"):
        start = _shown(form, "repeat_start")
    season = _shown(form, "season") or ""
    window = None
    if season == Season.CUSTOM:
        first, last = _shown(form, "season_start_month"), _shown(form, "season_end_month")
        window = (first, last) if first and last else None
    elif season:
        window = recurrence.season_window(season, home.hemisphere)
    return repeat_text.summary(
        mode=mode,
        unit=_shown(form, "repeat_unit") or "",
        interval=_shown(form, "repeat_interval"),
        start=start,
        season=window,
    )


class TaskForm(forms.ModelForm[Task]):
    """A task: the title is the only required field; the rest is under the headings."""

    assignee = PersonChoiceField(label=_("Assignee"), queryset=User.objects.none(), required=False)
    item = ItemChoiceField(label=_("Item"), queryset=Item.objects.none(), required=False)

    due_on = forms.DateField(label=_("Due on"), required=False, widget=_DATE)
    # The repetition as one sentence (docs/screens/task-form.md): "Repeat every 3 months,
    # counting from the due date". The model keeps `repeat_mode`, made in `clean()`.
    repeats = forms.BooleanField(label=_("Repeat this task"), required=False)
    repeat_interval = forms.IntegerField(
        label=_("Repeat every"),
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    repeat_from = forms.ChoiceField(
        label=_("Count from"),
        required=False,
        choices=REPEAT_FROM_CHOICES,
        initial=RepeatMode.AFTER_LAST,
        widget=forms.RadioSelect,
    )
    repeat_start = forms.DateField(
        label=_("Starting on"),
        required=False,
        widget=_DATE,
        help_text=_("The same date as the due date above: changing one changes the other."),
    )
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
    # Amounts are typed the way the person writes them, as in projects (docs/adr/0051).
    labour_budget = MoneyField(label=_("Labour budget"), required=False)
    material_budget = MoneyField(label=_("Material budget"), required=False)
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
        "repeats",
        "repeat_interval",
        "repeat_unit",
        "repeat_from",
        "repeat_start",
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
        labels = {"room": _("Room"), "repeat_unit": _("Unit")}
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
        task = self.instance
        self.initial.setdefault("repeats", task.repeat_mode != RepeatMode.ONCE)
        if task.repeat_mode != RepeatMode.ONCE:
            self.initial.setdefault("repeat_from", task.repeat_mode)
        if task.pk:
            current = services.open_occurrence_of(task)
            self.initial.setdefault("due_on", current.due_on if current else None)
            self.initial.setdefault("season", task.season)
            if task.season == Season.CUSTOM:
                self.initial.setdefault("season_start_month", task.season_start_month)
                self.initial.setdefault("season_end_month", task.season_end_month)
        # One date in two places: the due date, and the date a fixed repetition counts from.
        self.initial.setdefault("repeat_start", self.initial.get("due_on"))
        self.home = home
        if self.instance.pk:
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
        self._clean_repeat(data)
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

    def _clean_repeat(self, data: dict[str, Any]) -> None:
        """The sentence back to the model: `repeat_mode`, and one due date.

        Without script every field is sent: what the choices do not use is ignored, as the
        page says. Unticked, the task is done once; its interval and unit are kept as they
        were. Counting from the due date, the date may be typed in either of its two
        fields: the one changed wins; two different changes are refused.
        """
        repeats = data.pop("repeats", False)
        repeat_from = data.pop("repeat_from", "") or RepeatMode.AFTER_LAST
        start = data.pop("repeat_start", None)
        if not repeats:
            data["repeat_mode"] = self.instance.repeat_mode = RepeatMode.ONCE
            if data.get("repeat_interval") is None:
                data["repeat_interval"] = self.instance.repeat_interval or 1
            return
        data["repeat_mode"] = repeat_from
        # The model's own checks, run after `clean()`, read the mode from the instance.
        self.instance.repeat_mode = repeat_from
        if data.get("repeat_interval") is None:
            self.add_error("repeat_interval", _("Give how often the task comes back."))
        if repeat_from != RepeatMode.FIXED:
            return
        start_changed = "repeat_start" in self.changed_data
        due_changed = "due_on" in self.changed_data
        if start_changed and not due_changed:
            data["due_on"] = start
        elif start_changed and start != data.get("due_on"):
            self.add_error("repeat_start", _("Give the same date as the due date."))

    def summary(self) -> str:
        """The repetition in one sentence, from the values shown (`repeat_text`)."""
        return repeat_summary(self, self.home)
