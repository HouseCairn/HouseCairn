"""`makemessages` with the options that keep the catalogs free of needless diffs.

Two pull requests that both add a string must merge without a conflict in a
catalog (docs/adr/0013). So:

- Each Django app has its own catalog, `<app>/locale/<language>/LC_MESSAGES/django.po`,
  and a string goes to the catalog of the app that owns the file it is in: the app's
  own directory, or its templates under `templates/<app>/`. Everything else (the
  shell, the shared templates, the project modules) goes to the catalog of `core`.
  Two pull requests that add strings to two apps touch two different files.
- A catalog has no source locations, which change with every edit of a file, no
  wrapping, which re-flows an entry when its neighbour changes, and no
  `POT-Creation-Date`, which changes at every run.

Run it from `src/housecairn`; `--app <name>` limits it to the strings of one app.
"""

import os
import re
from pathlib import Path
from typing import Any, cast

from django.conf import settings
from django.core.management.base import CommandError, CommandParser
from django.core.management.commands.makemessages import Command as MakeMessagesCommand

POT_CREATION_DATE = re.compile(r'^"POT-Creation-Date:[^\n]*\\n"\n', re.MULTILINE)
SHARED_APP = "core"
TEMPLATES_DIR = "templates"


def apps_dir() -> Path:
    return Path(settings.BASE_DIR)


def is_app(name: str) -> bool:
    return (apps_dir() / name / "apps.py").is_file()


def owner(path: str | os.PathLike[str]) -> str:
    """The app whose catalog holds the strings of a source file."""
    try:
        parts = Path(os.path.abspath(path)).relative_to(apps_dir().resolve()).parts
    except ValueError:
        return SHARED_APP
    if len(parts) > 2 and parts[0] == TEMPLATES_DIR and is_app(parts[1]):
        return parts[1]
    if len(parts) > 1 and is_app(parts[0]):
        return parts[0]
    return SHARED_APP


def locale_dir(app: str) -> str:
    return str(apps_dir().resolve() / app / "locale")


class Command(MakeMessagesCommand):
    def add_arguments(self, parser: CommandParser) -> None:
        super().add_arguments(parser)
        parser.add_argument(
            "--app",
            help="Only the strings of this app (its directory and templates/<app>/).",
        )
        parser.set_defaults(no_location=True, no_wrap=True, no_obsolete=True)

    def handle(self, *args: Any, **options: Any) -> None:
        self.only_app = options.get("app")
        if self.only_app and not is_app(self.only_app):
            raise CommandError(f"No app named {self.only_app!r} in {apps_dir()}.")
        super().handle(*args, **options)

    def find_files(self, root: str) -> list[Any]:
        """Route every file to the catalog of its app, never by the nearest `locale/`."""
        files = []
        # django-stubs misses the attributes of TranslatableFile (file, dirpath, path).
        for found in cast(list[Any], super().find_files(root)):
            app = owner(found.path)
            if self.only_app and app != self.only_app:
                continue
            target = locale_dir(app)
            os.makedirs(target, exist_ok=True)
            if target not in self.locale_paths:
                self.locale_paths.append(target)
            files.append(self.translatable_file_class(found.dirpath, found.file, target))
        return sorted(files)

    def write_po_file(self, potfile: str, locale: str) -> None:
        super().write_po_file(potfile, locale)
        pofile = Path(potfile).parent / locale / "LC_MESSAGES" / f"{self.domain}.po"
        text = pofile.read_text(encoding="utf-8")
        stripped = POT_CREATION_DATE.sub("", text)
        if stripped != text:
            pofile.write_text(stripped, encoding="utf-8")
