"""Tasks, their occurrences, contractors and attachments (docs/adr/0031 to 0034).

A task is the thing to do ("change the smoke detector battery"); an occurrence is one
time it has to be done, with its due date and its outcome. A task that repeats always
has exactly one open occurrence; closing it creates the next.
"""

import datetime
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from housecairn.core.models import BaseModel
from housecairn.homes.models import HomeOwnedModel
from housecairn.rooms.models import Item, Room, notes_field
from housecairn.tasks import recurrence
from housecairn.tasks.storage import attachment_storage

PROCEDURE_MAX_LENGTH = 20000
MAX_ATTACHMENTS_PER_TASK = 30


class Priority(models.TextChoices):
    LOW = "low", _("Low")
    NORMAL = "normal", _("Normal")
    HIGH = "high", _("High")


class RepeatMode(models.TextChoices):
    ONCE = recurrence.ONCE, _("Once")
    FIXED = recurrence.FIXED, _("Fixed date")
    AFTER_LAST = recurrence.AFTER_LAST, _("After the last time")


class RepeatUnit(models.TextChoices):
    DAY = recurrence.DAY, _("days")
    WEEK = recurrence.WEEK, _("weeks")
    MONTH = recurrence.MONTH, _("months")
    YEAR = recurrence.YEAR, _("years")


class Status(models.TextChoices):
    PLANNED = "planned", _("Planned")
    DONE = "done", pgettext_lazy("task", "Done")
    POSTPONED = "postponed", _("Postponed")
    SKIPPED = "skipped", _("Skipped")


OPEN_STATUSES = (Status.PLANNED, Status.POSTPONED)
CLOSED_STATUSES = (Status.DONE, Status.SKIPPED)


def _money(label: Any) -> models.DecimalField[Any, Any]:
    return models.DecimalField(
        label,
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )


class Contractor(HomeOwnedModel):
    """Someone who does work in the home: a trade, a company, a neighbour."""

    name = models.CharField(_("name"), max_length=120)
    trade = models.CharField(_("trade"), max_length=120, blank=True)
    note = notes_field(_("note"))

    class Meta:
        verbose_name = _("contractor")
        verbose_name_plural = _("contractors")
        ordering = ["name", "created_at", "id"]

    def __str__(self) -> str:
        return self.name


class Task(HomeOwnedModel):
    """Something to do, once or again and again. Only the title is required."""

    title = models.CharField(_("title"), max_length=200)
    room = models.ForeignKey(
        Room, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks"
    )
    item = models.ForeignKey(
        Item, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks"
    )
    priority = models.CharField(
        _("priority"), max_length=8, choices=Priority.choices, default=Priority.NORMAL
    )
    estimated_minutes = models.PositiveIntegerField(
        _("estimated duration (minutes)"),
        null=True,
        blank=True,
        validators=[MaxValueValidator(60 * 24 * 30)],
    )
    labour_budget = _money(_("labour budget"))
    material_budget = _money(_("material budget"))
    notes = notes_field(_("notes"))
    # Markdown, rendered safely (docs/adr/0031): HTML escaped, `http(s)` links only.
    procedure = models.TextField(
        _("procedure"), blank=True, validators=[MaxLengthValidator(PROCEDURE_MAX_LENGTH)]
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("assignee"),
    )
    contractor = models.ForeignKey(
        Contractor,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
        verbose_name=_("contractor"),
    )
    repeat_mode = models.CharField(
        _("repeat"), max_length=12, choices=RepeatMode.choices, default=RepeatMode.ONCE
    )
    repeat_unit = models.CharField(
        _("unit"), max_length=8, choices=RepeatUnit.choices, default=RepeatUnit.MONTH
    )
    repeat_interval = models.PositiveIntegerField(
        _("every"), default=1, validators=[MinValueValidator(1)]
    )
    season_start_month = models.PositiveSmallIntegerField(
        _("season starts in"), null=True, blank=True
    )
    season_end_month = models.PositiveSmallIntegerField(_("season ends in"), null=True, blank=True)
    hide_days_before = models.PositiveSmallIntegerField(
        _("hide until this many days before"),
        default=0,
        validators=[MaxValueValidator(365)],
        help_text=_("0 shows the task as soon as it exists."),
    )
    # First due date of a fixed series: it carries the day of the month (docs/adr/0031).
    series_start = models.DateField(null=True, blank=True, editable=False)
    # Room for the materials with quantities of a task: they belong to the stock (a later
    # lot) and will hang off the task by their own table.

    class Meta:
        verbose_name = _("task")
        verbose_name_plural = _("tasks")
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["home", "created_at"], name="task_home_created")]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(season_start_month__isnull=True, season_end_month__isnull=True)
                    | models.Q(season_start_month__isnull=False, season_end_month__isnull=False)
                ),
                name="task_season_both_or_none",
            )
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def rule(self) -> recurrence.Rule:
        return recurrence.Rule(
            mode=self.repeat_mode,
            unit=self.repeat_unit,
            interval=self.repeat_interval,
            season_start=self.season_start_month,
            season_end=self.season_end_month,
        )

    @property
    def repeats(self) -> bool:
        return self.repeat_mode != RepeatMode.ONCE

    def clean(self) -> None:
        super().clean()
        errors: dict[str, Any] = {}
        room, item, contractor = self.room, self.item, self.contractor
        if room and self.home_id and room.home_id != self.home_id:
            errors["room"] = _("This room is not in this home.")
        if item and self.home_id and item.home_id != self.home_id:
            errors["item"] = _("This item is not in this home.")
        elif item and room and item.room_id != room.id:
            errors["item"] = _("This item is not in this room.")
        if contractor and self.home_id and contractor.home_id != self.home_id:
            errors["contractor"] = _("This contractor is not in this home.")
        found = recurrence.problems(self.rule)
        if "interval" in found:
            errors["repeat_interval"] = _("This interval is out of range.")
        if "season" in found:
            errors["season_start_month"] = _("Give the first and the last month of the season.")
        if errors:
            raise ValidationError(errors)


class Occurrence(HomeOwnedModel):
    """One time a task has to be done: when, and how it ended."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="occurrences")
    due_on = models.DateField(_("due on"), null=True, blank=True)
    # The day the occurrence starts to show: the due date minus the task's masking delay.
    visible_from = models.DateField(null=True, blank=True, editable=False)
    status = models.CharField(
        _("status"), max_length=10, choices=Status.choices, default=Status.PLANNED
    )
    # Status before the occurrence was closed, to restore it on undo (docs/adr/0033).
    status_before = models.CharField(max_length=10, blank=True, editable=False)
    postponed_from = models.DateField(null=True, blank=True, editable=False)
    completed_on = models.DateField(_("done on"), null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actual_cost = _money(_("actual cost"))
    completion_note = notes_field(_("note"))
    # The occurrence whose closing created this one.
    follows = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="next_occurrence"
    )

    class Meta:
        verbose_name = _("occurrence")
        verbose_name_plural = _("occurrences")
        ordering = ["due_on", "created_at", "id"]
        indexes = [
            models.Index(fields=["home", "status", "due_on"], name="occ_home_status_due"),
            models.Index(fields=["task", "status"], name="occ_task_status"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["task"],
                condition=models.Q(status__in=["planned", "postponed"], deleted_at__isnull=True),
                name="one_open_occurrence_per_task",
            )
        ]

    def __str__(self) -> str:
        return f"{self.task_id} {self.due_on or '-'} {self.status}"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def is_overdue(self, today: datetime.date) -> bool:
        return self.is_open and self.due_on is not None and self.due_on < today


class TodayGroup(models.TextChoices):
    URGENCY = "urgency", _("Urgency")
    ROOM = "room", _("Room")
    PERSON = "person", _("Person")
    CALENDAR = "calendar", _("Calendar")


class Horizon(models.IntegerChoices):
    WEEK = 7, _("1 week")
    TWO_WEEKS = 14, _("2 weeks")
    MONTH = 30, _("1 month")
    TWO_MONTHS = 60, _("2 months")
    QUARTER = 90, _("3 months")


class DisplayPreference(BaseModel):
    """How a person wants the Today screen laid out (docs/adr/0037).

    It belongs to the person, not to a home: one setting for every home they open.
    A person who never changed anything has no row; the defaults below apply.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="display_preference"
    )
    today_group = models.CharField(
        _("group by"), max_length=10, choices=TodayGroup.choices, default=TodayGroup.URGENCY
    )
    horizon_days = models.PositiveSmallIntegerField(
        _("look ahead"), choices=Horizon.choices, default=Horizon.WEEK
    )
    show_overdue = models.BooleanField(_("overdue"), default=True)
    show_upcoming = models.BooleanField(_("coming up"), default=True)
    show_season = models.BooleanField(_("in season"), default=True)

    class Meta:
        verbose_name = _("display preference")
        verbose_name_plural = _("display preferences")


def attachment_path(attachment: "Attachment", filename: str) -> str:
    """Storage name: home and attachment identifiers only, never a name chosen by the sender."""
    return f"{attachment.home_id}/{attachment.id}{filename}"


class Attachment(HomeOwnedModel):
    """A photo or a file attached to a task, or to one of its occurrences (docs/adr/0034)."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    occurrence = models.ForeignKey(
        Occurrence, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments"
    )
    # Name shown to people, cleaned of any path and control character; never used on disk.
    name = models.CharField(_("name"), max_length=120)
    file = models.FileField(
        storage=attachment_storage, upload_to=attachment_path, max_length=200, editable=False
    )
    thumbnail = models.FileField(
        storage=attachment_storage,
        upload_to=attachment_path,
        max_length=200,
        editable=False,
        blank=True,
    )
    content_type = models.CharField(max_length=100, editable=False)
    is_image = models.BooleanField(default=False, editable=False)
    size_bytes = models.PositiveIntegerField(editable=False)
    width = models.PositiveIntegerField(null=True, editable=False)
    height = models.PositiveIntegerField(null=True, editable=False)

    class Meta:
        verbose_name = _("attachment")
        verbose_name_plural = _("attachments")
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return self.name
