"""The summary of what a refused form got wrong (design guide, Forms).

`{% include "components/form_errors.html" with form=form only %}` is the one component of
every form of the application. It lists, at the top of the form, one
line per error: the label of the field, linked to the field by its `id`, and the message;
the errors that belong to no field come first, without a link. It draws nothing for a form
with no error. The summary takes the focus when the page opens (`autofocus`, which the
browser and HTMX both honour on a fresh page and on a swapped fragment), so the person
sees why the form was refused without scrolling to look for the field.

Pass every form of the block that is sent together: `with form=form formset=materials only`
(a formset of the same block is optional).
"""

from dataclasses import dataclass
from typing import Any

from django import template
from django.core.exceptions import NON_FIELD_ERRORS

register = template.Library()


@dataclass(frozen=True)
class ErrorLine:
    label: str
    message: str
    href: str


def _lines(form: Any) -> list[ErrorLine]:
    lines: list[ErrorLine] = []
    if hasattr(form, "forms"):  # a formset: its own errors, then those of each form
        lines += [ErrorLine("", str(message), "") for message in form.non_form_errors()]
        for sub_form in form.forms:
            lines += _lines(sub_form)
        return lines
    if not form.is_bound:
        return lines
    lines += [ErrorLine("", str(message), "") for message in form.non_field_errors()]
    for name, errors in form.errors.items():
        if name == NON_FIELD_ERRORS:
            continue
        label, href = name, ""
        if name in form.fields:
            bound = form[name]
            label = str(bound.label or name)
            # A list of boxes or buttons has no id of its own: Django gives its first one `_0`.
            target = bound.id_for_label or (f"{bound.auto_id}_0" if bound.auto_id else "")
            if target:
                href = f"#{target}"
        lines += [ErrorLine(label, str(message), href) for message in errors]
    return lines


@register.simple_tag
def error_lines(*forms: Any) -> list[ErrorLine]:
    """The lines of the summary: those of each form, formsets included, in order."""
    return [line for form in forms if form not in (None, "") for line in _lines(form)]
