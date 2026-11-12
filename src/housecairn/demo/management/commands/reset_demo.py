"""`manage.py reset_demo`: back to the known state of a demonstration instance.

Refused unless `HOUSECAIRN_DEMO` is true: it erases every account and every home. With
`--if-empty`, it only runs on an instance without any account (the first start).
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from housecairn.demo import reset
from housecairn.homes.management.commands.load_demo_data import LANGUAGES


class Command(BaseCommand):
    help = "Erase everything and load the demonstration accounts and home (HOUSECAIRN_DEMO)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--if-empty",
            action="store_true",
            help="Only on an instance without any account: the first start.",
        )
        parser.add_argument(
            "--language",
            choices=LANGUAGES,
            help="Language of the demonstration home; the default language of the instance "
            "otherwise.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["if_empty"] and not reset.is_empty():
            self.stdout.write("The instance has accounts: nothing done.")
            return
        try:
            reset.reset(language=options["language"])
        except reset.DemoOffError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write("Demonstration instance reset.")
