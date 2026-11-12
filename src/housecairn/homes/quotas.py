"""Quotas of the files of a home (docs/adr/0042).

What a home holds is measured on disk, in the directories of the home that every app
declares (`homes.files`): photos of rooms and items, attachments of tasks, label photos
of the stock, their thumbnails, and the files of deleted records that wait for the purge.
Measuring the disk, not the rows, counts what an app forgets to record and what deletion
leaves behind, so that deleting and adding again cannot fill the disk.

Every way to store a file goes through `room_for`, which locks the home, checks the
quota with the new file counted, and keeps the lock while the file is written. The
numbers are all an administrator sees of a home: no name, no file, no content.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext as _

from housecairn.homes import files
from housecairn.homes.models import Home
from housecairn.instance.config import get_setting

MB = 1024 * 1024
# A thumbnail goes with its file: it takes space, but is not a file of its own.
THUMBNAIL_SUFFIX = "-thumb.jpg"


@dataclass(frozen=True)
class Usage:
    bytes: int
    files: int


@dataclass(frozen=True)
class Limits:
    bytes: int
    files: int


def limits() -> Limits:
    return Limits(
        bytes=int(get_setting("home_storage_mb")) * MB, files=int(get_setting("home_max_files"))
    )


def _walk(directory: Path) -> Iterator[os.DirEntry[str]]:
    # Symbolic links are neither followed nor counted: the app never makes one.
    try:
        entries = list(os.scandir(directory))
    except (FileNotFoundError, NotADirectoryError):
        return
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            yield from _walk(Path(entry.path))
        elif entry.is_file(follow_symlinks=False):
            yield entry


def usage(home_id: UUID) -> Usage:
    """Bytes and files the home holds on disk, across every declared folder."""
    size = count = 0
    for directory in files.home_directories(home_id):
        if directory.parent.name == "exports":
            continue  # archives made for a download (homes.jobs) are not data of the home
        for entry in _walk(directory):
            try:
                size += entry.stat(follow_symlinks=False).st_size
            except FileNotFoundError:  # removed while counting
                continue
            if not entry.name.endswith(THUMBNAIL_SUFFIX):
                count += 1
    return Usage(bytes=size, files=count)


def check(home: Home, *, size: int, new_files: int = 1) -> None:
    """ValidationError when `size` more bytes and `new_files` more files exceed a quota."""
    held, allowed = usage(home.id), limits()
    if new_files and held.files + new_files > allowed.files:
        raise ValidationError(
            _(
                "This home already holds %(count)d files, its limit: delete some, "
                "or ask the administrator of the instance for more."
            ),
            params={"count": allowed.files},
            code="quota_files",
        )
    if held.bytes + size > allowed.bytes:
        raise ValidationError(
            _(
                "There is no room left for this file: the files of this home take "
                "%(used)s of %(limit)s. Delete some, or ask the administrator of the "
                "instance for more."
            ),
            params={"used": filesizeformat(held.bytes), "limit": filesizeformat(allowed.bytes)},
            code="quota_bytes",
        )
    _check_demo_total(size)


def _check_demo_total(size: int) -> None:
    """On a demonstration instance, a quota for all the homes together (docs/adr/0071).

    Anyone may create homes there, each with its own quota: without it, the disk would only
    be bounded by the number of homes a visitor creates before the nightly reset.
    """
    from housecairn.demo import mode

    if not mode.is_on():
        return
    held = sum(usage(home_id).bytes for home_id in Home.all_objects.values_list("id", flat=True))
    if held + size > mode.INSTANCE_STORAGE_BYTES:
        raise ValidationError(
            _(
                "This is a demonstration instance: its files take %(used)s of the %(limit)s "
                "it allows. Try again after the nightly reset."
            ),
            params={
                "used": filesizeformat(held),
                "limit": filesizeformat(mode.INSTANCE_STORAGE_BYTES),
            },
            code="quota_demo",
        )


@dataclass(frozen=True)
class HomeUsage:
    """What the administrator sees of a home: its identifier and numbers, nothing else."""

    id: UUID
    bytes: int
    files: int
    percent: int  # of the quota closer to its limit


def by_home() -> list[HomeUsage]:
    """Every home, the fullest first; never a name, a member or a file name."""
    allowed = limits()
    rows = []
    for home_id in Home.objects.order_by("created_at").values_list("id", flat=True):
        held = usage(home_id)
        percent = max(held.bytes * 100 // allowed.bytes, held.files * 100 // allowed.files)
        rows.append(HomeUsage(home_id, held.bytes, held.files, int(percent)))
    return sorted(rows, key=lambda row: (-row.percent, -row.bytes))


@contextmanager
def room_for(home: Home, *, size: int, new_files: int = 1) -> Iterator[None]:
    """Check the quota and hold the home while the caller writes its file and its row.

    An update that changes nothing takes the lock (the row on PostgreSQL, the database
    on SQLite, where a read would take none) until the end of the transaction: two
    uploads to the same home wait for each other, and both cannot pass the check together.
    """
    with transaction.atomic():
        Home.all_objects.filter(pk=home.pk).update(updated_at=F("updated_at"))
        check(home, size=size, new_files=new_files)
        yield
