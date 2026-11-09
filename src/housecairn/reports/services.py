"""Rules of reports (docs/adr/0002, 0047).

Every member of the home reports, a read-only one included: it is the only thing a reader
writes, and it changes nothing else. A reader sees the reports they made and no others; a
member who writes sees them all, makes one into a task, closes it and reopens it.
"""

from typing import Any
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from housecairn.accounts.models import User
from housecairn.audit import services as audit
from housecairn.core.text import without_control_characters
from housecairn.homes import quotas
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.reports.models import (
    ATTENTION_STATUSES,
    CLOSED_STATUSES,
    MAX_OPEN_PER_REPORTER,
    TITLE_MAX_LENGTH,
    Report,
    ReportStatus,
)
from housecairn.rooms import images
from housecairn.rooms.models import Item, Room
from housecairn.rooms.services import _read_upload
from housecairn.stock.models import Article
from housecairn.tasks import services as task_services
from housecairn.tasks.models import Task

AnyUser = User | AnonymousUser

_RELATED = ("reporter", "room", "item__room", "article", "task")


def reporter_name(user: User | None) -> str:
    """How the person is shown: their display name, else their name, else nothing of their
    address. Never an e-mail address."""
    if user is None:
        return _("a former member")
    shown = str(getattr(user, "display_name", "") or user.get_full_name()).strip()
    return shown or _("a member")


def _require_member(actor: AnyUser, home: Home) -> None:
    if home_services.role_of(actor, home) is None:
        raise PermissionDenied


def _require_write(actor: AnyUser, home: Home) -> None:
    if not home_services.can_write(actor, home):
        raise PermissionDenied


# ---------- reading ----------


def reports_of(home: Home) -> models.QuerySet[Report]:
    return Report.objects.filter(home=home).select_related(*_RELATED)


def visible_reports(actor: AnyUser, home: Home) -> models.QuerySet[Report]:
    """Every report for a member who writes; only their own for anyone else."""
    reports = reports_of(home)
    if home_services.can_write(actor, home):
        return reports
    if not actor.is_authenticated:
        return reports.none()
    return reports.filter(reporter=actor)


def open_reports(home: Home) -> models.QuerySet[Report]:
    return reports_of(home).filter(status__in=ATTENTION_STATUSES)


def open_count(home: Home) -> int:
    return Report.objects.filter(home=home, status__in=ATTENTION_STATUSES).count()


def places_for_forms(home: Home) -> dict[str, models.QuerySet[Any]]:
    """What the "where" list offers: the rooms, the items and the stock items of the home."""
    return {
        "room": Room.objects.filter(home=home).order_by("position", "name", "id"),
        "item": Item.objects.filter(home=home)
        .select_related("room")
        .order_by("room__position", "room__name", "name", "id"),
        "article": Article.objects.filter(home=home).order_by("name", "id"),
    }


def place_of(room: Room | None, item: Item | None, article: Article | None) -> str:
    """The words that say where, written once: `Kitchen`, `Kitchen · Boiler`, `Stock · Filter`."""
    if item is not None:
        return f"{item.room.name} · {item.name}"
    if room is not None:
        return str(room.name)
    if article is not None:
        return _("Stock · %(name)s") % {"name": article.name}
    return ""


# ---------- writing ----------


def _clean_title(value: str) -> str:
    title = " ".join(without_control_characters(" ".join(str(value).split())).split())
    if not title:
        raise ValidationError({"title": _("Say what is wrong.")})
    if len(title) > TITLE_MAX_LENGTH:
        raise ValidationError(
            {"title": _("At most %(max)d characters.") % {"max": TITLE_MAX_LENGTH}}
        )
    return title


def _store_photo(report: Report, upload: UploadedFile) -> None:
    processed = images.process(_read_upload(upload))
    report.photo_content_type = processed.content_type
    report.photo_size_bytes = len(processed.data)
    with quotas.room_for(report.home, size=len(processed.data) + len(processed.thumbnail)):
        report.photo.save(processed.extension, ContentFile(processed.data), save=False)
        report.thumbnail.save("-thumb.jpg", ContentFile(processed.thumbnail), save=False)
        try:
            report.save()
        except Exception:
            report.photo.delete(save=False)
            report.thumbnail.delete(save=False)
            raise


def create_report(
    actor: AnyUser,
    home: Home,
    *,
    title: str,
    room: Room | None = None,
    item: Item | None = None,
    article: Article | None = None,
    photo: UploadedFile | None = None,
) -> Report:
    """Report a problem. The place is optional, and at most one of room, item, stock item."""
    _require_member(actor, home)
    assert isinstance(actor, User)  # noqa: S101 - a member is a signed-in user
    if sum(place is not None for place in (room, item, article)) > 1:
        raise ValidationError({"place": _("Choose one place.")})
    for found in (room, item, article):
        if found is not None and found.home_id != home.id:
            raise ValidationError({"place": _("Nothing with this identifier in this home.")})
    title = _clean_title(title)
    if (
        Report.objects.filter(
            home=home, reporter=actor, status__in=(ReportStatus.OPEN, ReportStatus.TASK)
        ).count()
        >= MAX_OPEN_PER_REPORTER
    ):
        raise ValidationError(
            _("You already have %(max)d reports waiting: they must be dealt with first.")
            % {"max": MAX_OPEN_PER_REPORTER}
        )
    with transaction.atomic():
        report = Report(
            home=home,
            reporter=actor,
            title=title,
            room=room,
            item=item,
            article=article,
            place=place_of(room, item, article),
        )
        report.full_clean(exclude=["photo", "thumbnail"])
        if photo is None:
            report.save()
        else:
            _store_photo(report, photo)
        audit.record_object("report.created", actor=actor, home_id=home.id, title=report.title)
        transaction.on_commit(lambda: _alert(report.id))
    return report


def _alert(report_id: UUID) -> None:
    """Tell the people who write, by their channels, in the background (docs/adr/0043)."""
    from django_q.tasks import async_task

    async_task("housecairn.notifications.alerts.report_created", str(report_id))


@transaction.atomic
def make_task(actor: AnyUser, report: Report) -> Task:
    """Make the report into a task with no date, and keep the link between the two."""
    _require_write(actor, report.home)
    if report.status != ReportStatus.OPEN:
        raise ValidationError(_("Only an open report can be made into a task."))
    where = report.where
    task = task_services.create_task(
        actor,
        report.home,
        title=report.title,
        room=where if isinstance(where, Room) else None,
        item=where if isinstance(where, Item) else None,
    )
    changed = Report.objects.filter(pk=report.pk, status=ReportStatus.OPEN).update(
        status=ReportStatus.TASK, task=task, updated_at=timezone.now()
    )
    if not changed:  # somebody else dealt with it first: undo the task too
        raise ValidationError(_("Only an open report can be made into a task."))
    report.status, report.task = ReportStatus.TASK, task
    audit.record_object("report.converted", actor=actor, home_id=report.home_id, title=report.title)
    return task


@transaction.atomic
def close_report(actor: AnyUser, report: Report, *, resolution: str) -> Report:
    """Close the report as resolved or as needing no action."""
    _require_write(actor, report.home)
    if resolution not in CLOSED_STATUSES:
        raise ValidationError({"resolution": _("Choose resolved or closed without action.")})
    changed = Report.objects.filter(
        pk=report.pk, status__in=(ReportStatus.OPEN, ReportStatus.TASK)
    ).update(
        status=resolution,
        closed_at=timezone.now(),
        closed_by=actor if isinstance(actor, User) else None,
        updated_at=timezone.now(),
    )
    if not changed:
        raise ValidationError(_("This report is already closed."))
    report.refresh_from_db()
    audit.record_object(
        "report.closed",
        actor=actor,
        home_id=report.home_id,
        title=report.title,
        kind=str(resolution),
    )
    return report


@transaction.atomic
def reopen_report(actor: AnyUser, report: Report) -> Report:
    """Reopen a closed report; it goes back to its task if it had one."""
    _require_write(actor, report.home)
    back = (
        ReportStatus.TASK
        if report.task is not None and report.task.deleted_at is None
        else ReportStatus.OPEN
    )
    changed = Report.objects.filter(pk=report.pk, status__in=CLOSED_STATUSES).update(
        status=back, closed_at=None, closed_by=None, updated_at=timezone.now()
    )
    if not changed:
        raise ValidationError(_("Only a closed report can be reopened."))
    report.refresh_from_db()
    return report
