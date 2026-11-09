"""Mark an email address verified, for an instance that cannot send email (docs/adr/0020).

An invitation handed over by hand is only accepted by an account that verified the invited
address. Without outgoing email nobody can, so the administrator of the server does it here.
"""

from typing import Any

from allauth.account.models import EmailAddress
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from housecairn.audit import services as audit


class Command(BaseCommand):
    help = (
        "Mark an email address as verified, for an instance that sends no email. "
        "With --primary, also make it the primary address of its account."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("address", help="The address to verify, case ignored.")
        parser.add_argument(
            "--primary",
            action="store_true",
            help="Also make it the primary address, and so the sign-in address, of its account.",
        )

    @transaction.atomic
    def handle(self, *args: Any, address: str, primary: bool, **options: Any) -> None:
        records = list(
            EmailAddress.objects.select_for_update()
            .select_related("user")
            .filter(email__iexact=address.strip())
        )
        if not records:
            raise CommandError("No account has this address.")
        if len(records) > 1:
            ids = ", ".join(sorted(str(record.user_id) for record in records))
            raise CommandError(
                f"{len(records)} accounts have this address: nothing changed. Account ids: {ids}."
            )
        record = records[0]
        changed: list[str] = []
        if not record.verified:
            if not record.set_verified():
                raise CommandError("allauth refuses to verify this address: nothing changed.")
            changed.append("verified")
        if primary and not record.primary:
            record.set_as_primary(conditional=False)
            changed.append("primary")
        if not changed:
            self.stdout.write("Nothing to change: the address is already as asked.")
            return
        audit.record("account.email_verified", target=record.user)
        self.stdout.write(f"Account {record.user_id}: address marked {' and '.join(changed)}.")
