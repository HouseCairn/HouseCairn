"""Restore the archive of a home, from the command line of the instance (docs/adr/0048).

For the administrator moving homes from one instance to another: unlike the web page,
every person of the archive who has an account here, with the same e-mail address, is
attached again (memberships, assignees, who did a task). Nobody gets an account they did
not have; the others are listed, left unattributed.
"""

from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from housecairn.homes import restore


class Command(BaseCommand):
    help = "Restore the archive of a home (Export all data) as a new home."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("archive", type=Path, help="the zip file of the export")
        parser.add_argument(
            "--owner", required=True, help="e-mail address of the account that will own the home"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        owner = (
            get_user_model().objects.filter(email__iexact=options["owner"], is_active=True).first()
        )
        if owner is None:
            raise CommandError("No active account has this address; create it first.")
        try:
            with options["archive"].open("rb") as handle:
                result = restore.restore_home(owner, handle, match_people=True)
        except OSError as exc:
            raise CommandError(f"Cannot read the archive: {exc.strerror}") from None
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from None
        self.stdout.write(f"Restored home {result.home.id}.")
        for name in result.matched:
            self.stdout.write(f"Attached again: {name}")
        for name in result.unattributed:
            self.stdout.write(f"Left unattributed (no account here): {name}")
