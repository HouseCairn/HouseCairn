"""The library of task templates: common tasks of a home, ready to add (docs/adr/0049).

The library is `task_templates.yaml`, next to this file, versioned with the code: each
template has a title in English and in French, the type of item and of room it is
found in, an indicative interval with its source, a season, a duration and indicative
materials. `tests/test_task_templates.py` checks it against the JSON Schema published in
the documentation (`docs/_static/schemas/task-templates.schema.json`); this module
checks again what it relies on when it loads it.

A template becomes an ordinary task of the home, in the language of the person who adds
it, repeating after the last time it was done: once added, nothing ties it to the
library, and the person changes it as any other task.
"""

import datetime
import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from django.db import transaction
from django.utils import translation
from django.utils.translation import gettext as _

from housecairn.homes.models import Home
from housecairn.tasks import services
from housecairn.tasks.models import RepeatMode, RepeatUnit, Season, Task

LIBRARY = Path(__file__).with_name("task_templates.yaml")
LANGUAGES = ("en", "fr")


@dataclass(frozen=True)
class Text:
    """A text in each language of the library."""

    en: str
    fr: str

    def get(self, language: str | None = None) -> str:
        language = (language or translation.get_language() or "en").split("-")[0]
        return self.fr if language == "fr" else self.en


@dataclass(frozen=True)
class Equipment:
    id: str
    name: Text


@dataclass(frozen=True)
class Template:
    id: str
    equipment: str
    title: Text
    item_kind: str
    room_kinds: tuple[str, ...]
    interval: int
    unit: str
    minutes: int
    materials: tuple[Text, ...]
    source_title: str
    source_url: str
    season: str = ""
    procedure: Text | None = None
    region: str = ""
    note: Text | None = None

    def notes(self, language: str | None = None) -> str:
        """The notes of the task made from this template, in `language`."""
        with translation.override(language or translation.get_language()):
            lines = []
            if self.note is not None:
                lines.append(self.note.get(language))
            if self.materials:
                lines.append(
                    _("Material: %(list)s.")
                    % {"list": ", ".join(m.get(language) for m in self.materials)}
                )
            lines.append(
                _("Interval from: %(title)s, %(url)s")
                % {"title": self.source_title, "url": self.source_url}
            )
        return "\n\n".join(lines)

    def task_fields(self, language: str | None = None) -> dict[str, Any]:
        """The fields of `services.create_task` for this template."""
        return {
            "title": self.title.get(language),
            "repeat_mode": RepeatMode.AFTER_LAST,
            "repeat_unit": self.unit,
            "repeat_interval": self.interval,
            "season": self.season,
            "estimated_minutes": self.minutes,
            "procedure": self.procedure.get(language) if self.procedure else "",
            "notes": self.notes(language),
        }


@dataclass(frozen=True)
class Library:
    equipment: tuple[Equipment, ...]
    templates: tuple[Template, ...]

    def get(self, template_id: str) -> Template | None:
        return next((t for t in self.templates if t.id == template_id), None)

    def of_equipment(self, equipment_id: str) -> list[Template]:
        return [t for t in self.templates if t.equipment == equipment_id]


def _text(raw: Any) -> Text:
    if not isinstance(raw, dict) or set(raw) != set(LANGUAGES):
        raise ValueError(f"A text of the library needs exactly {LANGUAGES}: {raw!r}")
    return Text(en=str(raw["en"]), fr=str(raw["fr"]))


def parse(raw: Any) -> Library:
    """The library from its YAML document; ValueError when it is not one this code reads."""
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("The library of task templates is not of version 1.")
    equipment = tuple(Equipment(id=str(e["id"]), name=_text(e["name"])) for e in raw["equipment"])
    known = {e.id for e in equipment}
    templates = []
    for entry in raw["templates"]:
        every = entry["every"]
        template = Template(
            id=str(entry["id"]),
            equipment=str(entry["equipment"]),
            title=_text(entry["title"]),
            item_kind=str(entry["applies_to"]["item_kind"]),
            room_kinds=tuple(entry["applies_to"]["room_kinds"]),
            interval=int(every["interval"]),
            unit=str(every["unit"]),
            minutes=int(entry["minutes"]),
            materials=tuple(_text(m) for m in entry["materials"]),
            source_title=str(entry["source"]["title"]),
            source_url=str(entry["source"]["url"]),
            season=str(entry.get("season", "")),
            procedure=_text(entry["procedure"]) if "procedure" in entry else None,
            region=str(entry.get("region", "")),
            note=_text(entry["note"]) if "note" in entry else None,
        )
        if template.equipment not in known:
            raise ValueError(f"{template.id}: unknown equipment {template.equipment!r}.")
        if template.unit not in RepeatUnit.values or template.interval < 1:
            raise ValueError(f"{template.id}: the interval is not one a task takes.")
        if template.season and template.season not in Season.values:
            raise ValueError(f"{template.id}: unknown season {template.season!r}.")
        if not template.source_url.startswith("https://"):
            raise ValueError(f"{template.id}: the source must be an https address.")
        if template.region and template.note is None:
            raise ValueError(f"{template.id}: a regional rule needs a note that says so.")
        templates.append(template)
    ids = [t.id for t in templates]
    if len(set(ids)) != len(ids) or len(known) != len(equipment):
        raise ValueError("Two templates, or two pieces of equipment, share an identifier.")
    return Library(equipment=equipment, templates=tuple(templates))


@functools.cache
def library() -> Library:
    """The library shipped with this version, read once."""
    with LIBRARY.open(encoding="utf-8") as handle:
        return parse(yaml.safe_load(handle))


@transaction.atomic
def add_templates(
    actor: Any,
    home: Home,
    template_ids: list[str],
    *,
    room: Any = None,
    due_on: datetime.date | None = None,
    language: str | None = None,
) -> list[Task]:
    """Create one task of `home` per template, in one transaction; ValueError for an unknown id.

    The tasks are made by `services.create_task`, with its checks and its audit entries.
    """
    found = library()
    templates = []
    for template_id in dict.fromkeys(template_ids):
        template = found.get(template_id)
        if template is None:
            raise ValueError(template_id)
        templates.append(template)
    return [
        services.create_task(
            actor, home, due_on=due_on, room=room, **template.task_fields(language)
        )
        for template in templates
    ]


def add_equipment(
    actor: Any, home: Home, equipment_ids: list[str], *, language: str | None = None
) -> list[Task]:
    """The tasks of every template of the equipment checked when the home is created."""
    found = library()
    ids = [t.id for e in equipment_ids for t in found.of_equipment(e)]
    return add_templates(actor, home, ids, language=language)
