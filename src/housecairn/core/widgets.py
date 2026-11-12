"""Form widgets shared by several areas of the application."""

from collections.abc import Callable
from typing import Any

from django import forms
from django.template.loader import render_to_string


class ChipSelectMultiple(forms.SelectMultiple):
    """A multiple choice among the records of a home: search, pick, chips (docs/adr/0063).

    It posts exactly what `SelectMultiple` posts (one `name=value` per choice), so the field, the
    form and the services behind it do not change. Without script the page shows the native
    `<select multiple>`, its options grouped when `group_by` names a group (the room of an item);
    `static/js/chip-select.js` replaces it with a search field, a list of suggestions and one
    removable chip per choice, and keeps the select, hidden, as the thing that is submitted.
    """

    template_name = "components/chip_select.html"
    allow_multiple_selected = True

    def __init__(
        self,
        attrs: dict[str, Any] | None = None,
        choices: Any = (),
        *,
        group_by: Callable[[Any], str] | None = None,
    ) -> None:
        """`group_by(record)` names the group of an option of a model field, if there is one."""
        super().__init__(attrs, choices)
        self.group_by = group_by

    def optgroups(
        self, name: str, value: list[str], attrs: dict[str, Any] | None = None
    ) -> list[tuple[str | None, list[dict[str, Any]], int | None]]:
        groups: dict[str | None, list[dict[str, Any]]] = {}
        index = 0
        for option_value, option_label in self.choices:
            if option_value is None or option_value == "":
                continue
            instance = getattr(option_value, "instance", None)
            group = self.group_by(instance) if self.group_by and instance is not None else None
            members = groups.setdefault(group, [])
            members.append(
                self.create_option(
                    name,
                    option_value,
                    str(option_label),
                    str(option_value) in value,
                    index,
                    subindex=len(members) if group is not None else None,
                    attrs=attrs,
                )
            )
            index += 1
        return [(group, members, i) for i, (group, members) in enumerate(groups.items())]

    def _render(self, template_name: str, context: dict[str, Any], renderer: Any = None) -> str:
        """The page templates are in the project's directory, which the form renderer ignores."""
        return render_to_string(template_name, context)
