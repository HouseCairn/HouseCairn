"""API v1 of tasks, occurrences, contractors and attachments (docs/adr/0004, 0031-0034).

Validation only; rules live in `services`. Everything the screens do is done here. The
resources sit in one module each; this package exposes the ones the router mounts.
"""

from housecairn.tasks.api.attachments import AttachmentViewSet
from housecairn.tasks.api.contractors import ContractorViewSet
from housecairn.tasks.api.occurrences import OccurrenceViewSet
from housecairn.tasks.api.tasks import TaskViewSet
from housecairn.tasks.api.today import MyHomeView, PreferencesView, TodayView

__all__ = [
    "AttachmentViewSet",
    "ContractorViewSet",
    "MyHomeView",
    "OccurrenceViewSet",
    "PreferencesView",
    "TaskViewSet",
    "TodayView",
]
