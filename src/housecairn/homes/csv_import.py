"""Import of CSV tables into a home: rooms, items, tasks, stock and contractors (docs/adr/0048).

The columns are those of the CSV export (`homes.csv_export`): a file exported, opened in a
spreadsheet and saved again comes back. Every file is read as hostile, and nothing is
written before the person confirms:

1. each file: at most `MAX_BYTES` and `MAX_ROWS` rows for all of them, UTF-8 with or without
   a byte order mark, separated by commas (the export's format, decided for every CSV of
   the application), one header row naming known columns once;
2. each row: every cell parsed by the type of its field, the leading `'` that the export
   adds to a cell that would start a formula taken off again, every reference to a row of
   this home or of the files imported with it, never of another home;
3. then every row is written through the services of its app, as the forms do, in one
   transaction. The preview runs the same transaction and rolls it back: what it shows is
   exactly what the confirmation writes, and it writes nothing.

Between the preview and the confirmation of the screen, the text checked is kept on the
server (`ImportPreview`), named by a signed token, for one person and one home and
`PREVIEW_MINUTES` minutes.

A row whose `id` is a row already in this home is a duplicate: refused, never merged. The
identifier of a new row is always new; the `id` column only lets the other files refer to
it. A reference is the identifier of a row, or its exact name.
"""

import csv
import datetime
import hashlib
import hmac
import io
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from housecairn.accounts.names import person_name
from housecairn.homes import csv_export, exports, services
from housecairn.homes.csv_export import BOM, FORMULA_STARTS
from housecairn.homes.models import Home, ImportPreview

# 2 MB in all: room for 1,000 rows with long notes. The files are uploaded once, as files
# (which DATA_UPLOAD_MAX_MEMORY_SIZE does not count); the confirmation sends back only the
# token of the preview, so the cap holds up to it, whatever the text is written in.
MAX_BYTES = 2 * 1024 * 1024
# 1,000 rows for the files of one import: each row goes through the checks of its service
# in a savepoint, about 7 ms a row, and the confirmation runs them all again; 1,000 rows
# keep each request within seconds, far from the 30 s after which gunicorn stops a worker.
MAX_ROWS = 1_000
# How long the text of a preview waits for its confirmation, on the server.
PREVIEW_MINUTES = 30
PREVIEW_SALT = "housecairn.homes.csv_import.preview"
# Columns of the export that the import reads but does not write: made again here.
IGNORED = frozenset({"created_at", "updated_at", "position", "label_content_type", "currency"})


class ImportRefusedError(ValidationError):
    """A file cannot be imported at all; the message says why."""


class PreviewInvalidError(Exception):
    """No preview to confirm: expired, already confirmed, or of another person or home."""


Create = Callable[[Any, Home, dict[str, Any]], models.Model]


@dataclass(frozen=True)
class ImportEntity:
    """A table that can be imported: the CSV of the export of the same name.

    `fields` are the columns written, through `create`; `references` maps a column to the
    entity it names; `key` is the column that names a row (required, used to find it).
    """

    name: str
    model: type[models.Model]
    key: str
    fields: frozenset[str]
    create: Create
    references: dict[str, str] = field(default_factory=dict)
    label: Any = ""

    def section(self) -> exports.Section:
        found = exports.section_of_model(self.model)
        if found is None:  # pragma: no cover - checked by tests/test_csv_import.py
            raise LookupError(self.name)
        return found

    def columns(self) -> list[models.Field[Any, Any]]:
        """The fields of the columns of the CSV export of the same name."""
        return csv_export._columns(self.section())


# Entities in the order they are written: a reference only names an entity written before.
REGISTRY: dict[str, ImportEntity] = {}


def register(entity: ImportEntity) -> None:
    REGISTRY[entity.name] = entity


def entities() -> dict[str, ImportEntity]:
    """The importable tables, registered on first use (the models are loaded by then)."""
    if not REGISTRY:
        _register()
    return REGISTRY


# --- Reading a file -----------------------------------------------------------------------


@dataclass
class RowReport:
    line: int
    label: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return bool(self.errors)


@dataclass
class FileReport:
    entity: str
    label: str
    columns: list[tuple[str, str | None]] = field(default_factory=list)  # header, field
    error: str = ""
    rows: list[RowReport] = field(default_factory=list)

    @property
    def accepted(self) -> int:
        return sum(1 for row in self.rows if not row.refused)

    @property
    def refused(self) -> int:
        return sum(1 for row in self.rows if row.refused)

    @property
    def ignored_columns(self) -> list[str]:
        return [header for header, name in self.columns if name is None]


@dataclass
class Report:
    files: list[FileReport] = field(default_factory=list)
    written: bool = False

    @property
    def error(self) -> bool:
        return any(f.error for f in self.files)

    @property
    def accepted(self) -> int:
        return sum(f.accepted for f in self.files)

    @property
    def refused(self) -> int:
        return sum(f.refused for f in self.files)

    @property
    def can_confirm(self) -> bool:
        return not self.error and self.accepted > 0

    def as_data(self) -> dict[str, Any]:
        return {
            "written": self.written,
            "accepted": self.accepted,
            "refused": self.refused,
            "files": [
                {
                    "entity": f.entity,
                    "error": f.error or None,
                    "columns": dict(f.columns),
                    "accepted": f.accepted,
                    "refused": f.refused,
                    "rows": [
                        {
                            "line": r.line,
                            "label": r.label,
                            "status": "refused" if r.refused else "accepted",
                            "errors": r.errors,
                            "warnings": r.warnings,
                        }
                        for r in f.rows
                    ],
                }
                for f in self.files
            ],
        }


def decode(data: bytes) -> str:
    """The text of a file: UTF-8, with or without a byte order mark."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ImportRefusedError(
            _("This file is not in UTF-8. Save it again as “CSV UTF-8 (comma delimited)”.")
        ) from None
    return text.removeprefix(BOM)


def unneutralise(value: str) -> str:
    """A cell without the `'` the export puts before what a spreadsheet would run."""
    if value.startswith("'") and value[1:].startswith(FORMULA_STARTS):
        return value[1:]
    return value


def _header_names(entity: ImportEntity) -> dict[str, str]:
    """Header (folded) -> field: the name of the field, or its label in English or French."""
    names: dict[str, str] = {}
    for f in entity.columns():
        names[f.name.casefold()] = f.name
        for language in ("en", "fr"):
            with translation.override(language):
                names.setdefault(str(f.verbose_name).strip().casefold(), f.name)
    return names


def _read(
    entity: ImportEntity, text: str, report: FileReport, before: int = 0
) -> list[tuple[int, dict[str, str]]]:
    """The rows of a file; `before` is the number of rows of the files read before it."""
    text = text.removeprefix(BOM)
    if "\x00" in text:
        raise ImportRefusedError(_("This file is not a CSV table."))
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if header is None:
            raise ImportRefusedError(_("This file is empty."))
        if len(header) == 1 and ";" in header[0]:
            # What Excel writes on a system whose list separator is `;` (French, say).
            raise ImportRefusedError(
                _(
                    "This file is separated by semicolons. Save it again with commas: "
                    "see “Opening a table in a spreadsheet” in the help."
                )
            )
        known = _header_names(entity)
        mapped: dict[int, str] = {}
        for index, raw in enumerate(header):
            title = raw.strip()
            name = known.get(title.casefold())
            if name is None and title.casefold() in IGNORED | {"id"}:
                name = title.casefold()
            if name is not None and name in mapped.values():
                raise ImportRefusedError(
                    _("The column “%(column)s” appears twice.") % {"column": title[:60]}
                )
            report.columns.append((title[:60], name))
            if name is not None:
                mapped[index] = name
        if entity.key not in mapped.values():
            raise ImportRefusedError(
                _("The column “%(column)s” is missing: every row needs it.")
                % {"column": entity.key}
            )
        rows: list[tuple[int, dict[str, str]]] = []
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            if before + len(rows) >= MAX_ROWS:
                raise ImportRefusedError(
                    _(
                        "These files have more than %(count)s rows in all. Import them in "
                        "several times."
                    )
                    % {"count": MAX_ROWS}
                )
            values = {name: cells[i] if i < len(cells) else "" for i, name in mapped.items()}
            rows.append((reader.line_num, values))
    except csv.Error:
        raise ImportRefusedError(
            _("This file is not a valid CSV table (line %(line)s).") % {"line": reader.line_num}
        ) from None
    return rows


# --- Reading a cell -----------------------------------------------------------------------


def _choice(f: models.Field[Any, Any], text: str) -> str:
    folded = text.casefold()
    for value, label in f.flatchoices:
        if str(value).casefold() == folded:
            return str(value)
        for language in ("en", "fr"):
            with translation.override(language):
                if str(label).casefold() == folded:
                    return str(value)
    raise ValueError(_("“%(value)s” is not one of the choices.") % {"value": text[:60]})


def parse(f: models.Field[Any, Any], cell: str) -> Any:
    """The value of a field from the text of a cell; ValueError with a reason if it is not one."""
    text = unneutralise(cell)
    if text.strip() == "":
        if isinstance(f, models.CharField | models.TextField):
            return ""
        if f.null:
            return None
        if f.has_default():
            return f.get_default()
        raise ValueError(_("This value is required."))
    if isinstance(f, models.CharField | models.TextField):
        return _choice(f, text.strip()) if f.choices else text
    text = text.strip()
    if f.choices:
        return _choice(f, text)
    if isinstance(f, models.DateField):
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            raise ValueError(_("Give the date as YYYY-MM-DD.")) from None
    if isinstance(f, models.DecimalField):
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        try:
            number = Decimal(text)
        except InvalidOperation:
            raise ValueError(_("Give a number, with a point for decimals.")) from None
        if not number.is_finite():
            raise ValueError(_("Give a number, with a point for decimals."))
        return number
    if isinstance(f, models.BooleanField):
        if text.casefold() in {"true", "1", "yes", "oui", "vrai"}:
            return True
        if text.casefold() in {"false", "0", "no", "non", "faux"}:
            return False
        raise ValueError(_("Give true or false."))
    if isinstance(f, models.IntegerField):
        if not text.isdigit() or len(text) > 9:
            raise ValueError(_("Give a whole number."))
        return int(text)
    if isinstance(f, models.JSONField):
        try:
            return json.loads(text)
        except (ValueError, RecursionError):
            raise ValueError(_("This value is not valid.")) from None
    raise ValueError(_("This value is not valid."))  # pragma: no cover - no such column yet


# --- Running an import --------------------------------------------------------------------


class _Context:
    """What the rows of one import may refer to, and the people of the home."""

    def __init__(self, home: Home) -> None:
        self.home = home
        self.created: dict[str, dict[uuid.UUID, models.Model]] = {}
        self.refused: dict[str, set[uuid.UUID]] = {}
        members = get_user_model().objects.filter(memberships__home=home)
        self.people: dict[str, list[Any]] = {}
        for user in members:
            self.people.setdefault(person_name(user).casefold(), []).append(user)

    def live(self, entity: ImportEntity) -> "models.QuerySet[Any]":
        return entity.model._default_manager.filter(home=self.home)

    def resolve(self, target: ImportEntity, cell: str) -> models.Model | None:
        text = unneutralise(cell).strip()
        if not text:
            return None
        try:
            key = uuid.UUID(text)
        except ValueError:
            key = None
        if key is not None:
            if key in self.created.get(target.name, {}):
                return self.created[target.name][key]
            # A row already in this home (a duplicate refused above) is the row it names.
            found: models.Model | None = self.live(target).filter(pk=key).first()
            if found is None and key in self.refused.get(target.name, set()):
                raise ValueError(
                    _("It refers to a row of %(table)s that is refused.") % {"table": target.name}
                )
            if found is None:
                raise ValueError(
                    _("It refers to a row of %(table)s that is not in this home.")
                    % {"table": target.name}
                )
            return found
        matches: list[models.Model] = list(
            self.live(target).filter(**{f"{target.key}__iexact": text})[:2]
        )
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError(
                _("Two rows of %(table)s are named “%(name)s”: give its identifier.")
                % {"table": target.name, "name": text[:60]}
            )
        raise ValueError(
            _("No row of %(table)s in this home is named “%(name)s”.")
            % {"table": target.name, "name": text[:60]}
        )

    def person(self, cell: str) -> tuple[Any, str]:
        name = unneutralise(cell).strip()
        if not name:
            return None, ""
        found = self.people.get(name.casefold(), [])
        if len(found) == 1:
            return found[0], ""
        return None, _("No single member of this home is named “%(name)s”: left unassigned.") % {
            "name": name[:60]
        }


def _row(
    entity: ImportEntity,
    context: _Context,
    line: int,
    cells: dict[str, str],
    actor: Any,
    seen: set[uuid.UUID],
) -> tuple[RowReport, models.Model | None, uuid.UUID | None]:
    report = RowReport(line=line, label=unneutralise(cells.get(entity.key, "")).strip()[:120])
    key: uuid.UUID | None = None
    if cells.get("id", "").strip():
        try:
            key = uuid.UUID(cells["id"].strip())
        except ValueError:
            report.errors.append(_("id: this is not an identifier."))
    if key is not None and key in seen:
        report.errors.append(_("This identifier is given twice in the file."))
        return report, None, None
    if key is not None and context.live(entity).filter(pk=key).exists():
        report.errors.append(_("This row is already in this home: it is not imported again."))
        return report, None, key
    values: dict[str, Any] = {}
    columns = {f.name: f for f in entity.columns()}
    for name, cell in cells.items():
        f = columns.get(name)
        if f is None or name not in entity.fields:
            continue
        try:
            if name in entity.references:
                values[name] = context.resolve(entities()[entity.references[name]], cell)
            elif exports.person_reference(f):
                values[name], warning = context.person(cell)
                if warning:
                    report.warnings.append(warning)
            else:
                values[name] = parse(f, cell)
        except ValueError as exc:
            report.errors.append(f"{name}: {exc}")
    if report.errors:
        return report, None, key
    if context.live(entity).filter(**{f"{entity.key}__iexact": report.label}).exists():
        report.warnings.append(
            _("A row of this name is already in this home: this one is added as well.")
        )
    try:
        with transaction.atomic():
            created = entity.create(actor, context.home, values)
    except ValidationError as exc:
        if hasattr(exc, "error_dict"):
            for name, errors in exc.message_dict.items():
                report.errors.extend(f"{name}: {message}" for message in errors)
        else:
            report.errors.extend(exc.messages)
        return report, None, key
    return report, created, key


def run(actor: Any, home: Home, texts: dict[str, str], *, confirm: bool) -> Report:
    """Import the CSV `texts` (entity -> text) into `home`.

    Without `confirm`, the same import is run and rolled back: the report is the preview.
    With it, the rows accepted are written in one transaction. PermissionDenied for a
    person who cannot change the home.
    """
    from housecairn.audit import services as audit

    if not services.can_write(actor, home):
        raise PermissionDenied
    report = Report()
    parsed: dict[str, list[tuple[int, dict[str, str]]]] = {}
    for name, entity in entities().items():
        if name not in texts:
            continue
        file_report = FileReport(entity=name, label=str(entity.label))
        report.files.append(file_report)
        try:
            before = sum(len(found) for found in parsed.values())
            parsed[name] = _read(entity, texts[name], file_report, before)
        except ImportRefusedError as exc:
            file_report.error = " ".join(exc.messages)
    if report.error or not parsed:
        return report
    with transaction.atomic():
        context = _Context(home)
        for file_report in report.files:
            entity = REGISTRY[file_report.entity]
            created_here = context.created.setdefault(entity.name, {})
            refused_here = context.refused.setdefault(entity.name, set())
            seen: set[uuid.UUID] = set()
            for line, cells in parsed[entity.name]:
                row, created, key = _row(entity, context, line, cells, actor, seen)
                if key is not None:
                    seen.add(key)
                    if created is not None:
                        created_here[key] = created
                    elif row.refused:
                        refused_here.add(key)
                file_report.rows.append(row)
        if confirm and report.accepted:
            audit.record(
                "home.imported",
                actor=actor,
                home_id=home.id,
                count=report.accepted,
                fields=sorted(f.entity for f in report.files if f.accepted),
            )
            report.written = True
        else:
            transaction.set_rollback(True)
    return report


def texts_from_uploads(files: dict[str, Any]) -> dict[str, str]:
    """The text of each uploaded file (entity -> upload); ImportRefusedError past the cap."""
    total = sum(upload.size or 0 for upload in files.values())
    if total > MAX_BYTES:
        raise ImportRefusedError(too_large_message())
    texts: dict[str, str] = {}
    for name, upload in files.items():
        data = upload.read(MAX_BYTES + 1)
        texts[name] = decode(data)
    if sum(len(t.encode()) for t in texts.values()) > MAX_BYTES:
        raise ImportRefusedError(too_large_message())
    return texts


def too_large_message() -> str:
    return _("These files are too large: %(size)s MB at most in all.") % {
        "size": MAX_BYTES // (1024 * 1024)
    }


# --- Between the preview and the confirmation of the screen -------------------------------


def _digest(texts: dict[str, str]) -> str:
    canonical = json.dumps(texts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def purge_previews() -> None:
    """Remove the previews past their time; run every hour and on every new preview."""
    ImportPreview.all_objects.filter(expires_at__lte=timezone.now()).delete()


def keep_preview(actor: Any, home: Home, texts: dict[str, str]) -> str:
    """Keep `texts`, checked by a preview, for its confirmation; the signed token naming it.

    One preview a person and home: a new one replaces the one before.
    """
    purge_previews()
    ImportPreview.all_objects.filter(home=home, requested_by=actor).delete()
    digest = _digest(texts)
    preview = ImportPreview.objects.create(
        home=home,
        requested_by=actor,
        texts=texts,
        digest=digest,
        expires_at=timezone.now() + datetime.timedelta(minutes=PREVIEW_MINUTES),
    )
    return signing.dumps({"id": str(preview.id), "digest": digest}, salt=PREVIEW_SALT)


def take_preview(actor: Any, home: Home, token: str) -> tuple[ImportPreview, dict[str, str]]:
    """The preview a token names and its text, if it is this person's, in this home.

    PreviewInvalidError for a token that is not signed, too old, already used, of another
    person or another home, or whose text is not the one previewed.
    """
    try:
        signed = signing.loads(token, salt=PREVIEW_SALT, max_age=PREVIEW_MINUTES * 60)
        key = uuid.UUID(str(signed["id"]))
        digest = str(signed["digest"])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise PreviewInvalidError from None
    preview: ImportPreview | None = ImportPreview.objects.filter(
        pk=key, home=home, requested_by=actor, expires_at__gt=timezone.now()
    ).first()
    if preview is None or not isinstance(preview.texts, dict):
        raise PreviewInvalidError
    texts = {str(name): str(text) for name, text in preview.texts.items()}
    if not (
        hmac.compare_digest(digest, preview.digest) and hmac.compare_digest(digest, _digest(texts))
    ):
        raise PreviewInvalidError
    return preview, texts


def preview_invalid_message() -> str:
    return _(
        "This preview cannot be confirmed any more: it has expired, was already used, or "
        "was made for another person or another home. Choose the files again."
    )


# --- The entities ------------------------------------------------------------------------


def _create_article(actor: Any, home: Home, values: dict[str, Any]) -> models.Model:
    from housecairn.stock import services as stock

    return stock.create_article(actor, home, **values)


def _create_room(actor: Any, home: Home, values: dict[str, Any]) -> models.Model:
    from housecairn.rooms import services as rooms

    return rooms.create_room(actor, home, **values)


def _create_item(actor: Any, home: Home, values: dict[str, Any]) -> models.Model:
    from housecairn.rooms import services as rooms

    room = values.pop("room")
    if room is None:
        raise ValidationError({"room": _("Every item is in a room.")})
    return rooms.create_item(actor, room, **values)


def _create_contractor(actor: Any, home: Home, values: dict[str, Any]) -> models.Model:
    from housecairn.tasks import services as tasks

    return tasks.create_contractor(actor, home, **values)


def _create_task(actor: Any, home: Home, values: dict[str, Any]) -> models.Model:
    from housecairn.tasks import services as tasks

    # The date the series starts on is the date of its first occurrence.
    due_on = values.pop("series_start", None)
    return tasks.create_task(actor, home, due_on=due_on, **values)


def _register() -> None:
    from housecairn.rooms import services as rooms
    from housecairn.rooms.models import Item, Room
    from housecairn.stock import services as stock
    from housecairn.stock.models import Article
    from housecairn.tasks import services as tasks
    from housecairn.tasks.models import Contractor, Task

    for entity in (
        ImportEntity(
            "stock",
            Article,
            "name",
            stock.ARTICLE_FIELDS,
            _create_article,
            label=gettext_lazy("Stock"),
        ),
        ImportEntity(
            "rooms",
            Room,
            "name",
            rooms.ROOM_FIELDS | rooms.MEMORY_FIELDS,
            _create_room,
            references={"paint_article": "stock"},
            label=gettext_lazy("Rooms"),
        ),
        ImportEntity(
            "items",
            Item,
            "name",
            rooms.ITEM_FIELDS | {"room"},
            _create_item,
            references={"room": "rooms"},
            label=gettext_lazy("Items"),
        ),
        ImportEntity(
            "contractors",
            Contractor,
            "name",
            tasks.CONTRACTOR_FIELDS,
            _create_contractor,
            label=gettext_lazy("Contractors"),
        ),
        ImportEntity(
            "tasks",
            Task,
            "title",
            tasks.TASK_FIELDS | {"series_start"},
            _create_task,
            references={"room": "rooms", "item": "items", "contractor": "contractors"},
            label=gettext_lazy("Tasks"),
        ),
    ):
        register(entity)
