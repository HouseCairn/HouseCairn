"""Mark an email address verified, for an instance that cannot send email (docs/adr/0020).

An invitation handed over by hand is only accepted by an account that verified the invited
address. Without outgoing email nobody can, so the administrator of the server does it here.
"""

from typing import Any

from allauth.account.models import EmailAddress
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from housecairn.accounts.models import User
from housecairn.audit import services as audit
from housecairn.homes import services as home_services


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
        wanted = address.strip()
        records = list(
            EmailAddress.objects.select_for_update()
            .select_related("user")
            .filter(email__iexact=wanted)
        )
        changed: list[str] = []
        if not records:
            # `createsuperuser` (and any account made by code) sets `User.email` and records
            # nothing in allauth: such an account has no address record to verify yet.
            users = list(User.objects.select_for_update().filter(email__iexact=wanted))
            if not users:
                raise CommandError("No account has this address.")
            if len(users) == 1:
                home_services.verify_address(users[0], wanted)
                changed.append("verified")
                records = list(
                    EmailAddress.objects.select_related("user").filter(
                        user=users[0], email__iexact=wanted
                    )
                )
            else:
                records = [EmailAddress(user=user, email=user.email) for user in users]
        if len(records) > 1:
            ids = ", ".join(sorted(str(record.user_id) for record in records))
            raise CommandError(
                f"{len(records)} accounts have this address: nothing changed. Account ids: {ids}."
            )
        record = records[0]
        if not record.verified:
            if not record.set_verified():
                raise CommandError("allauth refuses to verify this address: nothing changed.")
            changed.append("verified")
        was_verified = "verified" not in changed
        if primary and not record.primary:
            record.set_as_primary(conditional=False)
            changed.append("primary")
        if not changed:
            self.stdout.write("Nothing to change: the address is already as asked.")
            return
        # Promoting an address that was already verified is not a verification: say so.
        action = "account.email_primary" if was_verified else "account.email_verified"
        audit.record(action, target=record.user)
        self.stdout.write(f"Account {record.user_id}: address marked {' and '.join(changed)}.")
