"""Translation checks: every source string has a non-fuzzy translation."""

import ast
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.core.management import call_command


@dataclass
class Entry:
    msgid: str = ""
    msgctxt: str | None = None
    msgstrs: list[str] = field(default_factory=list)
    fuzzy: bool = False

    @property
    def key(self) -> tuple[str | None, str]:
        return (self.msgctxt, self.msgid)


def parse_po(text: str) -> list[Entry]:
    """Parse the entries of a .po file (enough for checks, not a full parser)."""
    entries: list[Entry] = []
    current = Entry()
    target: str | None = None
    started = False

    def flush() -> None:
        nonlocal current, started
        if started:
            entries.append(current)
        current, started = Entry(), False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            target = None
            continue
        if line.startswith("#~"):
            continue  # obsolete entry
        if line.startswith("#,"):
            current.fuzzy = current.fuzzy or "fuzzy" in line
            continue
        if line.startswith("#"):
            continue
        keyword, _, rest = line.partition(" ")
        if line.startswith('"'):
            value = ast.literal_eval(line)
        else:
            value = ast.literal_eval(rest)
            target = keyword
            started = True
            if keyword.startswith("msgstr"):
                current.msgstrs.append("")
        if target == "msgctxt":
            current.msgctxt = (current.msgctxt or "") + value
        elif target in ("msgid", "msgid_plural"):
            if target == "msgid":
                current.msgid += value
        elif target and target.startswith("msgstr"):
            current.msgstrs[-1] += value
    flush()
    return entries


def po_files() -> Iterator[tuple[str, Path]]:
    for locale_dir in settings.LOCALE_PATHS:
        for language, _name in settings.LANGUAGES:
            if language == settings.LANGUAGE_CODE:
                continue
            yield language, Path(locale_dir) / language / "LC_MESSAGES" / "django.po"


def untranslated(path: Path) -> list[str]:
    """Problems in one catalog: missing, empty or fuzzy translations."""
    if not path.exists():
        return [f"{path.name}: catalog is missing"]
    problems = []
    for entry in parse_po(path.read_text(encoding="utf-8")):
        if entry.msgid == "":
            continue  # header
        if entry.fuzzy:
            problems.append(f"fuzzy: {entry.msgid!r}")
        elif not entry.msgstrs or any(s == "" for s in entry.msgstrs):
            problems.append(f"untranslated: {entry.msgid!r}")
    return problems


@contextmanager
def _restored(path: Path) -> Iterator[None]:
    backup = path.read_bytes() if path.exists() else None
    try:
        yield
    finally:
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(backup)


def missing_from_catalog(language: str, path: Path) -> list[str]:
    """Source strings absent from the committed catalog (needs GNU gettext)."""
    if shutil.which("xgettext") is None:
        raise RuntimeError("GNU gettext (xgettext) is required to scan the sources.")
    committed = (
        {e.key for e in parse_po(path.read_text(encoding="utf-8"))} if path.exists() else set()
    )
    cwd = Path.cwd()
    with _restored(path):
        os.chdir(settings.BASE_DIR)
        try:
            call_command(
                "makemessages",
                locale=[language],
                domain="django",
                no_obsolete=True,
                ignore_patterns=["static/*"],
                verbosity=0,
            )
        finally:
            os.chdir(cwd)
        scanned = {e.key for e in parse_po(path.read_text(encoding="utf-8")) if e.msgid}
    return sorted(repr(msgid) for _ctx, msgid in scanned - committed)
