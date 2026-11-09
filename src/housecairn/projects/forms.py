"""Forms of the project screens. Validation only; rules live in `services`."""

from typing import Any

from django import forms
from django.utils.dates import MONTHS
from django.utils.translation import gettext_lazy as _

from housecairn.projects.models import (
    ENVELOPE_YEARS,
    MAX_PROJECT_MINUTES,
    BudgetLine,
    Project,
    ProjectStatus,
    Quote,
    QuoteStatus,
)
from housecairn.rooms.models import Room
from housecairn.tasks import durations, files
from housecairn.tasks.models import Priority, Season, Task

_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
_MONEY = {"inputmode": "decimal", "autocomplete": "off"}
# Spaces that group thousands: the space, the no-break space and the narrow ones of French.
_GROUPING = dict.fromkeys(map(ord, " \u00a0\u2009\u202f"))


class MoneyField(forms.DecimalField):
    """An amount typed the way the person writes it: `1250.50` in English, `1 250,50` in French.

    The decimal mark follows the language (`localize`); the spaces that group thousands are
    dropped here, since Django only drops the separator of the language when the instance
    asks for thousand separators. Two decimals at most, as the model keeps; a scientific
    notation passes only while it stays within the digits of an amount.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("widget", forms.TextInput(attrs=_MONEY))
        super().__init__(max_digits=12, decimal_places=2, min_value=0, localize=True, **kwargs)

    def to_python(self, value: Any) -> Any:
        if isinstance(value, str):
            value = value.translate(_GROUPING)
        return super().to_python(value)


class ProjectForm(forms.ModelForm[Project]):
    """A project: the title is the only required field; the rest is under the headings."""

    rooms = forms.ModelMultipleChoiceField(
        label=_("Rooms concerned"),
        queryset=Room.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    season = forms.ChoiceField(
        label=_("Preferred season"),
        required=False,
        choices=[("", _("Any time")), *Season.choices],
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
        label=_("Estimated duration"),
        required=False,
        min_value=1,
        max_value=MAX_PROJECT_MINUTES,
    )
    duration_unit = forms.ChoiceField(
        label=_("Unit"), choices=durations.UNIT_CHOICES, initial=durations.DAY, required=False
    )
    budget = MoneyField(
        label=_("Budget"),
        required=False,
        help_text=_(
            "The amount you plan to spend. It becomes the first budget line, which you can "
            "split into materials and labour later."
        ),
    )

    field_order = [
        "title",
        "goal",
        "status",
        "priority",
        "rooms",
        "budget",
        "duration_value",
        "duration_unit",
        "season",
        "season_start_month",
        "season_end_month",
    ]

    class Meta:
        model = Project
        fields = ["title", "goal", "status", "priority"]
        widgets = {"goal": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args: Any, home: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        rooms = self.fields["rooms"]
        assert isinstance(rooms, forms.ModelMultipleChoiceField)  # noqa: S101 - narrows the type
        rooms.queryset = Room.objects.filter(home=home)
        hemisphere = home.get_hemisphere_display().lower()
        self.fields["season"].help_text = _(
            "The season follows the hemisphere of the home (%(hemisphere)s): change it in the "
            "settings of the home."
        ) % {"hemisphere": hemisphere}
        if not self.instance._state.adding:
            del self.fields["budget"]  # the budget lines are edited on the project page
            self.initial.setdefault("rooms", list(self.instance.rooms.all()))
            if self.instance.estimated_minutes:
                value, unit = durations.split(self.instance.estimated_minutes)
                self.initial.setdefault("duration_value", value)
                self.initial.setdefault("duration_unit", unit)

    def clean(self) -> dict[str, Any]:
        data: dict[str, Any] = super().clean() or {}
        value, unit = data.pop("duration_value", None), data.pop("duration_unit", None)
        minutes = None
        if value is not None:
            minutes = durations.to_minutes(value, unit or durations.DAY)
            if not 1 <= minutes <= MAX_PROJECT_MINUTES:
                self.add_error("duration_value", _("Give a duration between a minute and a year."))
        data["estimated_minutes"] = minutes
        if data.get("season") != Season.CUSTOM:
            data["season_start_month"] = data["season_end_month"] = None
        elif data.get("season_start_month") is None or data.get("season_end_month") is None:
            self.add_error("season_start_month", _("Give the first and the last month."))
        return data


class LineForm(forms.ModelForm[BudgetLine]):
    planned = MoneyField(label=_("Planned"), initial=0)
    paid = MoneyField(
        label=_("Paid"),
        initial=0,
        help_text=_("What has been paid so far. The committed amount comes from accepted quotes."),
    )

    class Meta:
        model = BudgetLine
        fields = ["label", "nature", "planned", "paid"]


class QuoteForm(forms.ModelForm[Quote]):
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
    amount = MoneyField(label=_("Amount"), initial=0)
    budget_line = forms.ModelChoiceField(
        label=_("Committed on"),
        queryset=BudgetLine.objects.none(),
        required=False,
        empty_label="—",
        help_text=_("The budget line an accepted quote is committed on."),
    )
    upload = forms.FileField(
        label=_("File of the quote"),
        required=False,
        widget=forms.FileInput(attrs={"accept": files.ACCEPT_ATTRIBUTE}),
    )

    field_order = [
        "contractor_name",
        "amount",
        "issued_on",
        "valid_until",
        "status",
        "budget_line",
        "note",
        "upload",
        "paperless_id",
        "paperless_url",
    ]

    class Meta:
        model = Quote
        fields = [
            "amount",
            "issued_on",
            "valid_until",
            "status",
            "note",
            "paperless_id",
            "paperless_url",
        ]
        widgets = {"issued_on": _DATE, "valid_until": _DATE}

    def __init__(self, *args: Any, project: Project, contractors: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        line = self.fields["budget_line"]
        assert isinstance(line, forms.ModelChoiceField)  # noqa: S101 - narrows the type
        line.queryset = BudgetLine.objects.filter(project=project)
        self.contractors = list(contractors)
        if not self.instance._state.adding:
            if self.instance.contractor is not None:
                self.initial.setdefault("contractor_name", self.instance.contractor.name)
            # The line an accepted quote is committed on is chosen again as it stands, so that
            # saving without a change is not refused for a missing line.
            self.initial.setdefault("budget_line", self.instance.budget_line_id)

    def clean(self) -> dict[str, Any]:
        data: dict[str, Any] = super().clean() or {}
        if data.get("status") == QuoteStatus.ACCEPTED and not data.get("budget_line"):
            self.add_error("budget_line", _("Choose the budget line the quote is committed on."))
        return data


class AcceptForm(forms.Form):
    """The line an accepted quote is committed on."""

    budget_line = forms.ModelChoiceField(
        label=_("Commit on"), queryset=BudgetLine.objects.none(), empty_label=None
    )

    def __init__(self, *args: Any, project: Project, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        field = self.fields["budget_line"]
        assert isinstance(field, forms.ModelChoiceField)  # noqa: S101 - narrows the type
        field.queryset = BudgetLine.objects.filter(project=project)


class StatusForm(forms.Form):
    status = forms.ChoiceField(
        choices=[s for s in QuoteStatus.choices if s[0] != QuoteStatus.ACCEPTED]
    )


class TaskAddForm(forms.Form):
    title = forms.CharField(label=_("New task"), max_length=200)
    due_on = forms.DateField(label=_("Due on"), required=False, widget=_DATE)
    room = forms.ModelChoiceField(
        label=_("Room"), queryset=Room.objects.none(), required=False, empty_label="—"
    )

    def __init__(self, *args: Any, home: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        field = self.fields["room"]
        assert isinstance(field, forms.ModelChoiceField)  # noqa: S101 - narrows the type
        field.queryset = Room.objects.filter(home=home)


class TaskAttachForm(forms.Form):
    task = forms.ModelChoiceField(
        label=_("Existing task"), queryset=Task.objects.none(), empty_label=None
    )

    def __init__(self, *args: Any, tasks: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        field = self.fields["task"]
        assert isinstance(field, forms.ModelChoiceField)  # noqa: S101 - narrows the type
        field.queryset = tasks


class PhotoForm(forms.Form):
    photo = forms.FileField(
        label=_("Photo"),
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )


class EnvelopeForm(forms.Form):
    year = forms.IntegerField(
        label=_("Year"), min_value=ENVELOPE_YEARS[0], max_value=ENVELOPE_YEARS[1]
    )
    amount = MoneyField(
        label=_("Envelope"),
        help_text=_("What you want to spend on work this year, in the currency of the home."),
    )


class FilterForm(forms.Form):
    """The filters at the head of the list; an invalid value is ignored."""

    q = forms.CharField(required=False, max_length=120)
    status = forms.ChoiceField(required=False, choices=[("", ""), *ProjectStatus.choices])
    priority = forms.ChoiceField(required=False, choices=[("", ""), *Priority.choices])
    season = forms.ChoiceField(required=False, choices=[("", ""), *Season.choices])
    room = forms.UUIDField(required=False)
