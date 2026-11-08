"""Forms of the room and item screens. Validation only; rules live in `services`."""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from housecairn.rooms.models import (
    Item,
    PhotoCategory,
    Room,
    RoomKind,
    validate_links,
)

_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class RoomForm(forms.ModelForm[Room]):
    """The type comes first and fills the name in, which stays editable (docs/adr/0045).

    `static/js/room-form.js` does the filling as the type is chosen; without script, a name
    left empty takes the label of the type. "Other" has no label to offer: the name is then
    the room's whole description.
    """

    class Meta:
        model = Room
        fields = ["kind", "name", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}
        help_texts = {
            "kind": _(
                "Sets the icon and the filters of the room and, later, the task templates "
                "offered for it. Choose Other if none fits."
            ),
            "name": _("Fills in by itself from the type; change it to name the room."),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False
        if self.instance._state.adding:
            kind_field = self.fields["kind"]
            assert isinstance(kind_field, forms.ChoiceField)  # noqa: S101 - narrows the type
            kind_field.choices = [("", _("Choose a type")), *RoomKind.choices]
            self.initial["kind"] = ""

    def clean(self) -> dict[str, Any]:
        data: dict[str, Any] = super().clean() or {}
        kind = data.get("kind")
        if not (data.get("name") or "").strip() and kind and "name" not in self.errors:
            if kind == RoomKind.OTHER:
                self.add_error("name", _("Give the room a name."))
            else:
                data["name"] = str(RoomKind(kind).label)
        return data


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
        help_texts = {
            "paint_colour": _("The colour as you would ask for it. Example: warm white."),
            "paint_brand": _("The make of the paint. Example: Acme Paints."),
            "paint_reference": _(
                "The reference or the colour code on the tin, to order the same one. "
                "Example: AC-1042."
            ),
            "paint_batch": _(
                "The batch number printed on the tin; shades can differ from one batch to "
                "another. Example: L23-0457."
            ),
            "paint_stock": _("What is left of it and where. Example: half a tin, in the garage."),
            "floor_covering": _(
                "What covers the floor, with its make and reference if you know them. "
                "Example: oak parquet, matt varnish."
            ),
            "wall_covering": _(
                "What covers the walls, under the paint if any. Example: lining paper, then paint."
            ),
            "memory_notes": _(
                "What the walls and floor hide, or anything else to remember about the work "
                "done. Example: water pipe along the north wall, 30 cm above the floor."
            ),
        }


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
        label=_("Category"),
        choices=PhotoCategory.choices,
        initial=PhotoCategory.GENERAL,
        help_text=_(
            "Behind the walls: pipes and cables photographed before the wall is closed, "
            "to know where not to drill. Other: say what it is in the caption."
        ),
    )
