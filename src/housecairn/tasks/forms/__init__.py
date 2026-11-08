"""Forms of the task screens. Validation only; rules live in `services`."""

from housecairn.tasks.forms.contractor import ContractorForm
from housecairn.tasks.forms.occurrence import AttachmentForm, CompletionForm, PostponeForm
from housecairn.tasks.forms.preferences import PreferencesForm
from housecairn.tasks.forms.task import TaskForm

__all__ = [
    "AttachmentForm",
    "CompletionForm",
    "ContractorForm",
    "PostponeForm",
    "PreferencesForm",
    "TaskForm",
]
