"""Background tasks of the core app (docs/adr/0008)."""

from django.utils import timezone


def heartbeat(label: str) -> dict[str, str]:
    """Demonstration task: proves the queue and the worker are wired up."""
    return {"label": label, "ran_at": timezone.now().isoformat()}
