"""Make a new push key pair for the instance (docs/adr/0066).

Every device is removed: it was subscribed with the old public key, so it would refuse the
messages of the new one. Each person adds their devices again from the screen of
notifications.
"""

from typing import Any

from django.core.management.base import BaseCommand

from housecairn.notifications import devices
from housecairn.notifications.models import Device


class Command(BaseCommand):
    help = "Make a new push key pair; every device is removed and subscribes again."

    def handle(self, *args: Any, **options: Any) -> None:
        count = Device.objects.count()
        devices.rotate_key()
        self.stdout.write(f"New push key made; {count} device(s) removed.")
