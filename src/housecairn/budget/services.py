"""The budget of a home, by room, project and maintenance task (docs/adr/0051).

Nothing here is stored: every figure is worked out when read, in `Decimal`, from the budget
lines and quotes of projects (docs/adr/0050) and from the estimates and actual costs of
tasks. A fixed number of queries loads a home, however many tasks it has; the sums are made
in Python, never by SQL `SUM`, which SQLite computes in floating point.

Views and API call these functions; neither holds a rule of its own.
"""

import datetime
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from housecairn.homes.models import Home
from housecairn.projects import services as project_services
from housecairn.projects.models import (
    ZERO,
    BudgetNature,
    Project,
    ProjectStatus,
    ProjectTask,
    Quote,
    QuoteStatus,
)
from housecairn.projects.services import Amounts
from housecairn.rooms.models import Room
from housecairn.tasks import recurrence
from housecairn.tasks import services as task_services
from housecairn.tasks.models import Occurrence, Status, Task

CENT = Decimal("0.01")
# A year is 12 months, 52 weeks or 365 days (docs/adr/0051).
PER_YEAR = {recurrence.MONTH: 12, recurrence.WEEK: 52, recurrence.DAY: 365, recurrence.YEAR: 1}
_OPEN = (Status.PLANNED, Status.POSTPONED)
# Dates worked out per task and year, at most: a daily task is 365 a year (docs/adr/0051).
PROJECTION_STEPS = 2_000


def cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- what is loaded ----------


@dataclass(frozen=True)
class ProjectRow:
    """A project as the budget counts it. An abandoned project plans nothing any more."""

    project: Project
    amounts: Amounts
    year: int
    rooms: tuple[Room, ...]
    by_nature: dict[str, Amounts]


@dataclass(frozen=True)
class TaskFigures:
    """What a maintenance task plans and costs over a period: whole occurrences only."""

    count: int  # done, open and projected
    material: Decimal  # planned
    labour: Decimal  # planned
    paid: Decimal
    missing: int  # done, with no cost typed: counted in the plan, paid as zero
    projected: int = 0  # of `count`: the times the repetition will still bring (no row yet)

    @property
    def amounts(self) -> Amounts:
        return Amounts(self.material + self.labour, ZERO, self.paid)


@dataclass(frozen=True)
class TaskRow:
    """A task that is not in a project: its estimate per time, its occurrences, its room."""

    task: Task
    room: Room | None
    material: Decimal
    labour: Decimal
    has_estimate: bool
    done: tuple[tuple[datetime.date | None, Decimal | None], ...]
    open: tuple[datetime.date | None, ...]
    today: datetime.date
    # Projections already worked out, by year: a row is read several times in a page.
    memo: dict[int, int] = field(default_factory=dict, compare=False, repr=False)

    @property
    def estimate(self) -> Decimal:
        return self.material + self.labour

    def projected(self, year: int) -> int:
        """How many times the repetition will still bring the task due in `year`.

        Counted after the open occurrence, were each one closed on its due date: the way
        the calendar projects it (`tasks.recurrence.next_due`, nothing is written). A year
        already over has none: only what happened counts. A task that does not repeat has
        none, nor one with no open date to count from.
        """
        if year not in self.memo:
            self.memo[year] = len(self._coming(year))
        return self.memo[year]

    def _coming(self, year: int) -> list[datetime.date]:
        task = self.task
        dates = [day for day in self.open if day]
        if year < self.today.year or not task.repeats or not dates:
            return []
        end = datetime.date(year, 12, 31)
        current = max(dates)
        if current > end:
            return []
        if task.repeat_mode == recurrence.FIXED and task.series_start and current.year < year:
            # A fixed series does not depend on the dates before: start at the last day of
            # the year before instead of walking every date from the open occurrence.
            current = datetime.date(year - 1, 12, 31)
        found: list[datetime.date] = []
        for _step in range(PROJECTION_STEPS):
            following = recurrence.next_due(
                task.rule, anchor=task.series_start, due_on=current, done_on=current
            )
            if following is None or following > end:
                break
            if following.year == year:
                found.append(following)
            current = following
        return found

    def figures(
        self,
        window: Callable[[datetime.date | None], bool],
        *,
        open_too: bool = True,
        year: int | None = None,
    ) -> TaskFigures:
        """The occurrences done in the window, and the open ones due in it (if asked).

        With a `year` the times the repetition will still bring in that year are added to the
        plan (none paid yet). The window and the year are the same period.
        """
        done = [(day, cost) for day, cost in self.done if window(day)]
        coming = [day for day in self.open if window(day)] if open_too else []
        projected = self.projected(year) if year is not None and open_too else 0
        count = len(done) + len(coming) + projected
        return TaskFigures(
            count,
            self.material * count,
            self.labour * count,
            sum((cost for _day, cost in done if cost is not None), ZERO),
            sum(1 for _day, cost in done if cost is None),
            projected,
        )

    @property
    def per_year(self) -> Decimal | None:
        """Times a year (to 28 digits), or `None` for a task off the calendar.

        For display only: the cost a year is not worked out from this rounded rate.
        """
        task = self.task
        if not task.repeats or task.repeat_unit not in PER_YEAR:
            return None
        return Decimal(PER_YEAR[task.repeat_unit]) / task.repeat_interval

    @property
    def annual_cost(self) -> Decimal | None:
        """The estimate times the times a year, rounded once, half up, to the cent.

        The multiplication comes before the division, so that no digit is lost before the
        one rounding: 0.24 every 48 years is 0.005 a year, which rounds to 0.01.
        """
        task = self.task
        if self.per_year is None or not self.has_estimate:
            return None
        return cents(self.estimate * PER_YEAR[task.repeat_unit] / task.repeat_interval)


@dataclass(frozen=True)
class Ledger:
    home: Home
    today: datetime.date
    projects: list[ProjectRow]
    tasks: list[TaskRow]
    envelopes: dict[int, Decimal]
    rooms: list[Room]

    @property
    def currency(self) -> str:
        return self.home.currency

    def years(self) -> list[int]:
        """Every year with a figure: of a project, a dated occurrence or an envelope."""
        found = {self.today.year, *self.envelopes, *(p.year for p in self.projects)}
        for row in self.tasks:
            found.update(day.year for day, _cost in row.done if day)
            found.update(day.year for day in row.open if day)
        return sorted(found, reverse=True)


def _split(amount: Decimal, parts: int) -> list[Decimal]:
    """Cents shared out evenly; the odd cents go to the first parts, so the sum is exact."""
    total = int(amount * 100)
    base, odd = divmod(total, parts)
    return [Decimal(base + (1 if i < odd else 0)) / 100 for i in range(parts)]


def share(amounts: Amounts, parts: int) -> list[Amounts]:
    columns = [
        _split(value, parts)
        for value in (
            amounts.planned,
            amounts.committed,
            amounts.paid,
            amounts.engaged,
            amounts.to_pay,
        )
    ]
    return [Amounts(*column) for column in zip(*columns, strict=True)]


def _day(cost_day: datetime.date | None, due: datetime.date | None) -> datetime.date | None:
    return cost_day or due


def _task_row(
    task: Task,
    room: Room | None,
    found: Iterable[tuple[str, Any, Any, Any]],
    today: datetime.date,
) -> TaskRow:
    """A task with its occurrences: (status, due, completed, cost) of each."""
    occurrences = list(found)
    done = tuple(
        (_day(completed, due), cost)
        for status, due, completed, cost in occurrences
        if status == "done"
    )
    coming = tuple(due for status, due, _completed, _cost in occurrences if status != "done")
    return TaskRow(
        task,
        room,
        task.material_budget or ZERO,
        task.labour_budget or ZERO,
        task.material_budget is not None or task.labour_budget is not None,
        done,
        coming,
        today,
    )


def task_row(task: Task, today: datetime.date | None = None) -> TaskRow | None:
    """One task, for its own page; `None` for a task of a project (its money is the project's)."""
    if ProjectTask.objects.filter(task=task, project__deleted_at__isnull=True).exists():
        return None
    found = Occurrence.objects.filter(task=task, status__in=[*_OPEN, Status.DONE]).values_list(
        "status", "due_on", "completed_on", "actual_cost"
    )
    return _task_row(task, None, found, today or task_services.today())


def load(home: Home, today: datetime.date | None = None) -> Ledger:
    """Everything the figures need, in a fixed number of queries."""
    today = today or task_services.today()
    rooms = list(Room.objects.filter(home=home).order_by("position", "name", "id"))
    room_of = {room.id: room for room in rooms}
    projects = list(
        project_services.projects_of(home).prefetch_related("rooms").order_by("created_at", "id")
    )
    lines = list(project_services.lines_of(home))
    quotes = list(
        Quote.objects.filter(
            home=home, project__deleted_at__isnull=True, status=QuoteStatus.ACCEPTED
        ).values_list("budget_line_id", "project_id", "amount", "issued_on")
    )
    links = ProjectTask.objects.filter(
        home=home, task__deleted_at__isnull=True, project__deleted_at__isnull=True
    ).values_list("task_id", "project_id")
    in_project: dict[UUID, UUID] = dict(links)
    tasks = list(Task.objects.filter(home=home).order_by("created_at", "id"))
    occurrences: dict[UUID, list[tuple[str, datetime.date | None, datetime.date | None, Any]]] = (
        defaultdict(list)
    )
    for task_id, status, due, completed, cost in Occurrence.objects.filter(
        home=home, status__in=[*_OPEN, Status.DONE]
    ).values_list("task_id", "status", "due_on", "completed_on", "actual_cost"):
        occurrences[task_id].append((status, due, completed, cost))

    # Projects: lines first (each is spent for the more of its quotes and its payments).
    committed: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    quote_days: dict[UUID, list[datetime.date]] = defaultdict(list)
    for line_id, project_id, amount, issued in quotes:
        committed[line_id] += amount
        if issued:
            quote_days[project_id].append(issued)
    task_days: dict[UUID, list[datetime.date]] = defaultdict(list)
    for task_id, project_id in in_project.items():
        for status, due, completed, _cost in occurrences.get(task_id, ()):
            day = _day(completed, due) if status == Status.DONE else due
            if day:
                task_days[project_id].append(day)
    by_project: dict[UUID, list[Any]] = defaultdict(list)
    for line in lines:
        by_project[line.project_id].append(line)
    rows = []
    for project in projects:
        abandoned = project.status == ProjectStatus.ABANDONED
        total = Amounts()
        by_nature: dict[str, Amounts] = {}
        for line in by_project[project.id]:
            planned = ZERO if abandoned else line.planned
            amounts = Amounts(planned, committed[line.id], line.paid)
            by_nature[line.nature] = by_nature.get(line.nature, Amounts()) + amounts
            total += amounts
        days = [*quote_days[project.id], *task_days[project.id]]
        year = min(days).year if days else timezone.localtime(project.created_at).year
        rooms_of = tuple(sorted(project.rooms.all(), key=lambda r: (r.position, r.name, r.id)))
        rows.append(ProjectRow(project, total, year, rooms_of, by_nature))

    # Maintenance: the tasks that are in no project (a project holds its own money).
    maintenance = []
    for task in tasks:
        if task.id in in_project:
            continue
        room = room_of.get(task.room_id) if task.room_id else None
        maintenance.append(_task_row(task, room, occurrences.get(task.id, ()), today))
    envelopes = {e.year: e.amount for e in project_services.envelopes_of(home)}
    return Ledger(home, today, rows, maintenance, envelopes, rooms)


# ---------- windows of time ----------


def in_year(year: int) -> Callable[[datetime.date | None], bool]:
    return lambda day: day is not None and day.year == year


def rolling_start(today: datetime.date) -> datetime.date:
    """First day of the 12 months ending today: the same day a year ago is outside."""
    return today - relativedelta(years=1) + datetime.timedelta(days=1)


def in_rolling(today: datetime.date) -> Callable[[datetime.date | None], bool]:
    start = rolling_start(today)
    return lambda day: day is not None and start <= day <= today


def anytime(_day_: datetime.date | None) -> bool:
    return True


# ---------- reports ----------


@dataclass(frozen=True)
class Line:
    """One row of a report: a room, a project, a task, a nature or a year."""

    id: UUID | None
    label: str
    amounts: Amounts
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Report:
    year: int
    currency: str
    lines: list[Line]
    total: Amounts
    years: list[int]
    note: dict[str, int] = field(default_factory=dict)


def _sum(items: Iterable[Amounts]) -> Amounts:
    total = Amounts()
    for item in items:
        total += item
    return total


def projects_in(ledger: Ledger, year: int | None) -> list[ProjectRow]:
    return [p for p in ledger.projects if year is None or p.year == year]


def maintenance_amounts(ledger: Ledger, year: int) -> Amounts:
    """The upkeep of a year: done, open and still to come by the repetition."""
    window = in_year(year)
    return _sum(row.figures(window, year=year).amounts for row in ledger.tasks)


def by_room(ledger: Ledger, year: int) -> Report:
    """Projects (their money shared evenly between their rooms) and maintenance, by room."""
    projects: dict[UUID | None, Amounts] = defaultdict(Amounts)
    upkeep: dict[UUID | None, Amounts] = defaultdict(Amounts)
    for row in projects_in(ledger, year):
        if row.rooms:
            for room, part in zip(row.rooms, share(row.amounts, len(row.rooms)), strict=True):
                projects[room.id] += part
        else:
            projects[None] += row.amounts
    window = in_year(year)
    for task in ledger.tasks:
        upkeep[task.room.id if task.room else None] += task.figures(window, year=year).amounts
    lines = []
    for candidate in [*ledger.rooms, None]:
        key = candidate.id if candidate else None
        if key not in projects and key not in upkeep:
            continue
        both = projects[key] + upkeep[key]
        lines.append(
            Line(
                key,
                candidate.name if candidate else "",
                both,
                {"projects": projects[key], "upkeep": upkeep[key]},
            )
        )
    return Report(
        year, ledger.currency, lines, _sum(line.amounts for line in lines), ledger.years()
    )


def by_project(ledger: Ledger) -> Report:
    lines = [
        Line(
            row.project.id,
            row.project.title,
            row.amounts,
            {"year": row.year, "status": row.project.status, "to_pay": row.amounts.to_pay},
        )
        for row in ledger.projects
    ]
    today = ledger.today.year
    return Report(
        today, ledger.currency, lines, _sum(line.amounts for line in lines), ledger.years()
    )


def by_task(ledger: Ledger, year: int) -> Report:
    """Maintenance tasks with an estimate or a cost: this year, in all, and per year."""
    window = in_year(year)
    lines, unlisted = [], 0
    for row in ledger.tasks:
        total = row.figures(anytime)
        if not row.has_estimate and total.paid == ZERO:
            unlisted += 1
            continue
        this_year = row.figures(window, year=year)
        lines.append(
            Line(
                row.task.id,
                row.task.title,
                this_year.amounts,
                {
                    "room": row.room.name if row.room else "",
                    "estimate": row.estimate if row.has_estimate else None,
                    "annual_cost": row.annual_cost,
                    "total_paid": total.paid,
                    "missing_costs": this_year.missing,
                },
            )
        )
    return Report(
        year,
        ledger.currency,
        lines,
        _sum(line.amounts for line in lines),
        ledger.years(),
        {"unlisted": unlisted},
    )


def by_nature(ledger: Ledger, year: int) -> list[Line]:
    """Materials, labour, rental, other. A cost typed on a done task has no nature: Other."""
    found: dict[str, Amounts] = {nature: Amounts() for nature in BudgetNature.values}
    for row in projects_in(ledger, year):
        for nature, amounts in row.by_nature.items():
            found[nature] += amounts
    window = in_year(year)
    for task in ledger.tasks:
        figures = task.figures(window, year=year)
        found[BudgetNature.MATERIAL] += Amounts(figures.material, ZERO, ZERO)
        found[BudgetNature.LABOUR] += Amounts(figures.labour, ZERO, ZERO)
        found[BudgetNature.OTHER] += Amounts(ZERO, ZERO, figures.paid)
    return [Line(None, nature, found[nature]) for nature in BudgetNature.values]


@dataclass(frozen=True)
class YearLine:
    year: int
    envelope: Decimal | None
    projects: Amounts
    upkeep: Amounts

    @property
    def total(self) -> Amounts:
        return self.projects + self.upkeep


def by_year(ledger: Ledger) -> list[YearLine]:
    return [
        YearLine(
            year,
            ledger.envelopes.get(year),
            _sum(p.amounts for p in projects_in(ledger, year)),
            maintenance_amounts(ledger, year),
        )
        for year in ledger.years()
    ]


@dataclass(frozen=True)
class EnvelopeReport:
    """The envelope of a year against what is planned, engaged and paid, projects and upkeep."""

    year: int
    envelope: Decimal | None
    projects: Amounts
    upkeep: Amounts
    # Room kept for a budget read from Sure (a later lot): nothing is fetched, ever, here.
    sure_budget: Decimal | None = None

    @property
    def total(self) -> Amounts:
        return self.projects + self.upkeep

    @property
    def left_to_plan(self) -> Decimal | None:
        return None if self.envelope is None else self.envelope - self.total.planned

    @property
    def left_to_spend(self) -> Decimal | None:
        return None if self.envelope is None else self.envelope - self.total.engaged


def envelope(ledger: Ledger, year: int) -> EnvelopeReport:
    return EnvelopeReport(
        year,
        ledger.envelopes.get(year),
        _sum(p.amounts for p in projects_in(ledger, year)),
        maintenance_amounts(ledger, year),
    )


@dataclass(frozen=True)
class Rolling:
    since: datetime.date
    until: datetime.date
    upkeep: Amounts
    missing: int


def rolling(ledger: Ledger) -> Rolling:
    """The last 12 months of upkeep. Payments on projects carry no date: they are left out."""
    window = in_rolling(ledger.today)
    figures = [row.figures(window, open_too=False) for row in ledger.tasks]
    return Rolling(
        rolling_start(ledger.today),
        ledger.today,
        _sum(f.amounts for f in figures),
        sum(f.missing for f in figures),
    )


# ---------- several homes ----------


def combined(homes: Iterable[Home], year: int | None = None) -> dict[str, dict[str, Any]]:
    """The year of every home, added by currency; currencies are never converted."""
    result: dict[str, dict[str, Any]] = {}
    for home in homes:
        ledger = load(home)
        report = envelope(ledger, year or ledger.today.year)
        entry = result.setdefault(
            home.currency, {"homes": [], "total": Amounts(), "envelope": None}
        )
        entry["homes"].append((home, report))
        entry["total"] += report.total
        if report.envelope is not None:
            entry["envelope"] = (entry["envelope"] or ZERO) + report.envelope
    return dict(sorted(result.items()))
