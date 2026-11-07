from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from housecairn.core import translations


class Command(BaseCommand):
    help = (
        "Fail if a catalog has an untranslated or fuzzy string; with --sources, also if "
        "a string of the code or templates is missing from the catalog."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--sources",
            action="store_true",
            help="Also scan the sources with makemessages (needs GNU gettext).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        problems: list[str] = []
        for language, path in translations.po_files():
            if options["sources"]:
                problems += [
                    f"{language}: not in catalog: {msgid}"
                    for msgid in translations.missing_from_catalog(language, path)
                ]
            problems += [f"{language}: {p}" for p in translations.untranslated(path)]
        if problems:
            raise CommandError("\n".join(problems))
        self.stdout.write("All strings are translated.")
