"""`makemessages` with the options that keep the catalogs free of needless diffs.

Two pull requests that both add a string must merge without a conflict in
`django.po` (docs/adr/0013). So the catalog has no source locations, which
change with every edit of a file, no wrapping, which re-flows an entry when
its neighbour changes, and no `POT-Creation-Date`, which changes at every run.
"""

import re
from pathlib import Path

from django.core.management.base import CommandParser
from django.core.management.commands.makemessages import Command as MakeMessagesCommand

POT_CREATION_DATE = re.compile(r'^"POT-Creation-Date:[^\n]*\\n"\n', re.MULTILINE)


class Command(MakeMessagesCommand):
    def add_arguments(self, parser: CommandParser) -> None:
        super().add_arguments(parser)
        parser.set_defaults(no_location=True, no_wrap=True, no_obsolete=True)

    def write_po_file(self, potfile: str, locale: str) -> None:
        super().write_po_file(potfile, locale)
        pofile = Path(potfile).parent / locale / "LC_MESSAGES" / f"{self.domain}.po"
        text = pofile.read_text(encoding="utf-8")
        stripped = POT_CREATION_DATE.sub("", text)
        if stripped != text:
            pofile.write_text(stripped, encoding="utf-8")
