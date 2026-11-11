"""Form widgets and fields shared by the task forms."""

from typing import Any, cast

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


# The value of the last choice of a list that can be added to in place ("Add a contractor…").
NEW = "new"


class _WithNewIterator(forms.models.ModelChoiceIterator):
    def __iter__(self) -> Any:
        yield from super().__iter__()
        yield (NEW, cast("AddInPlaceChoiceField", self.field).new_label)

    def __len__(self) -> int:
        return super().__len__() + 1


class AddInPlaceChoiceField(forms.ModelChoiceField[Any]):
    """A list of the home's records whose last choice adds one, without leaving the form.

    Choosing it shows the fields of the new record, right under the list
    (`data-shown-when="<field>=new"`, static/js/task-form.js); without script they are
    always there, and the server reads them only when that choice is sent. The form
    creates the record when it is saved, in the same transaction: a form refused leaves
    nothing behind (docs/developer/design-guide.md, "Adding to a list in place").
    `clean` gives `NEW` for that choice.
    """

    iterator = _WithNewIterator

    def __init__(self, *args: Any, new_label: Any, **kwargs: Any) -> None:
        self.new_label = new_label
        super().__init__(*args, **kwargs)

    def to_python(self, value: Any) -> Any:
        if value == NEW:
            return NEW
        return super().to_python(value)

    def validate(self, value: Any) -> None:
        if value != NEW:
            super().validate(value)

    def has_changed(self, initial: Any, data: Any) -> bool:
        if data == NEW:
            return True
        return super().has_changed(initial, data)


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
