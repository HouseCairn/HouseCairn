"""Issue the one-time code of the first-account screen and write it on standard error.

The container's entry point runs it at each start, after the migrations; it can also be
run by hand to get a fresh code (docs/adr/0055). It prints nothing and issues nothing
once an administrator exists or when `HOUSECAIRN_SETUP_SCREEN` is false.
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.urls import reverse

from housecairn.accounts import setup


class Command(BaseCommand):
    help = "Write a one-time code for the first-account screen in the process log."

    def handle(self, *args: Any, **options: Any) -> None:
        code = setup.issue_code()
        if code is None:
            return
        from django.conf import settings

        base = settings.HOUSECAIRN_SITE_URL.rstrip("/")
        address = f"{base}{reverse('setup')}" if base else reverse("setup")
        minutes = int(setup.CODE_LIFETIME.total_seconds() // 60)
        lines = [
            "",
            "HouseCairn has no administrator yet.",
            f"  Open {address}" + ("" if base else " on the address of your instance"),
            f"  First-account code: {code}",
            f"  The code works once and expires in {minutes} minutes; a new one is written",
            "  at each start, or by running: manage setup_code",
            "",
        ]
        self.stderr.write("\n".join(lines))
