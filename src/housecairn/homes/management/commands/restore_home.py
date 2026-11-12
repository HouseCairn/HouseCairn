"""Restore the archive of a home, from the command line of the instance (docs/adr/0048).

For the administrator moving homes from one instance to another: unlike the web page,
every person of the archive who has an account here, with the same e-mail address, is
attached again (memberships, assignees, who did a task). Nobody gets an account they did
not have; the others are listed, left unattributed.

With `--copy`, a copy with new identifiers that may sit next to the original
(docs/adr/0069): the owner given is its only member, and must be an owner of the home of
the archive when that home is on this instance.
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
        parser.add_argument(
            "--copy",
            action="store_true",
            help="restore as a copy, with new identifiers, next to the original; "
            "only the owner is a member of it",
        )
        parser.add_argument(
            "--name", default="", help='name of the copy (default: the name and "(copy)")'
        )

    def handle(self, *args: Any, **options: Any) -> None:
        owner = (
            get_user_model().objects.filter(email__iexact=options["owner"], is_active=True).first()
        )
        if owner is None:
            raise CommandError("No active account has this address; create it first.")
        if options["name"] and not options["copy"]:
            raise CommandError("--name names a copy: add --copy.")
        try:
            with options["archive"].open("rb") as handle:
                result = restore.restore_home(
                    owner,
                    handle,
                    match_people=True,
                    as_copy=options["copy"],
                    name=options["name"],
                )
        except OSError as exc:
            raise CommandError(f"Cannot read the archive: {exc.strerror}") from None
        except restore.CopyNotAllowedError as exc:
            raise CommandError(str(exc.message)) from None
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from None
        if options["copy"]:
            self.stdout.write(f"Restored home {result.home.id} as a copy: {result.home.name}.")
        else:
            self.stdout.write(f"Restored home {result.home.id}.")
        for name in result.matched:
            self.stdout.write(f"Attached again: {name}")
        for name in result.unattributed:
            self.stdout.write(f"Left unattributed (no account here): {name}")
