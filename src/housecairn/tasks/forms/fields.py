"""Form widgets and fields shared by the task forms."""

from typing import Any

from django import forms

from housecairn.accounts import names
from housecairn.accounts.models import User
from housecairn.accounts.names import person_name
from housecairn.rooms.models import Item

_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Several files from one chooser; each is checked by the service, by its content."""

    widget = MultipleFileInput

    def clean(self, data: Any, initial: Any = None) -> Any:
        clean_one = super().clean
        if isinstance(data, list | tuple):
            return [clean_one(entry, initial) for entry in data if entry]
        return [clean_one(data, initial)] if data else []


class ItemChoiceField(forms.ModelChoiceField[Item]):
    """An item, shown with its room: two items can have the same name."""

    def label_from_instance(self, obj: Item) -> str:
        return f"{obj.room.name} · {obj.name}"


class PersonChoiceField(forms.ModelChoiceField[User]):
    """A member of the home, by their name (docs/adr/0045).

    The address is added, in brackets, only to tell apart two members of the same name.
    """

    def label_from_instance(self, obj: User) -> str:
        shown = getattr(self, "_labels", None)
        if shown is None:
            shown = self._labels = names.labels(self.queryset or [])
        return shown.get(obj.pk) or person_name(obj)
