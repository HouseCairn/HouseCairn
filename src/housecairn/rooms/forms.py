"""Forms of the room and item screens. Validation only; rules live in `services`."""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from housecairn.rooms.models import (
    Item,
    PhotoCategory,
    Room,
    validate_links,
)

_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class RoomForm(forms.ModelForm[Room]):
    class Meta:
        model = Room
        fields = ["name", "kind", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}


class RoomMemoryForm(forms.ModelForm[Room]):
    class Meta:
        model = Room
        fields = [
            "paint_colour",
            "paint_brand",
            "paint_reference",
            "paint_batch",
            "paint_stock",
            "floor_covering",
            "wall_covering",
            "memory_notes",
        ]
        widgets = {"memory_notes": forms.Textarea(attrs={"rows": 4})}


def links_to_text(links: list[dict[str, str]]) -> str:
    return "\n".join(f"{link['url']} {link.get('label', '')}".strip() for link in links)


def text_to_links(text: str) -> list[dict[str, str]]:
    """One link per line: the address, then an optional label."""
    links: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        url, _sep, label = line.partition(" ")
        links.append({"url": url, "label": label.strip()} if label.strip() else {"url": url})
    return links


class ItemForm(forms.ModelForm[Item]):
    """The item's own fields; `room` is a choice among the rooms of its home."""

    room = forms.ModelChoiceField(
        label=_("Room"),
        queryset=Room.objects.none(),
        help_text=_("Where the item is. Choose another room to move it."),
    )
    links = forms.CharField(
        label=_("Links"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("One per line: the address, then a label if you like."),
    )

    class Meta:
        model = Item
        fields = [
            "room",
            "name",
            "kind",
            "brand",
            "model",
            "serial_number",
            "installed_on",
            "warranty_ends_on",
            "contract",
            "contract_url",
            "links",
            "notes",
        ]
        widgets = {
            "installed_on": _DATE,
            "warranty_ends_on": _DATE,
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args: Any, rooms: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        room_field = self.fields["room"]
        assert isinstance(room_field, forms.ModelChoiceField)  # noqa: S101 - narrows the type
        room_field.queryset = rooms
        if self.instance.pk:
            self.initial["links"] = links_to_text(self.instance.links)

    def clean_links(self) -> list[dict[str, str]]:
        links = text_to_links(self.cleaned_data.get("links") or "")
        try:
            validate_links(links)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc
        return links


class PhotoForm(forms.Form):
    file = forms.FileField(
        label=_("Photo"),
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    caption = forms.CharField(label=_("Caption"), max_length=200, required=False)
    category = forms.ChoiceField(
        label=_("Category"), choices=PhotoCategory.choices, initial=PhotoCategory.GENERAL
    )
