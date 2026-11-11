"""What a refused form got wrong, as lines: the summary at the top of the form and the banner.

A form that comes back as its page shows the lines in `components/form_errors.html`. A form
that is an action in place (it redirects to a page that already shows the record) says the
same thing in the banner of that page, each message led by the label of its field, so that
"This field is required." is never left alone (design guide, Forms).
"""

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import NON_FIELD_ERRORS


@dataclass(frozen=True)
class ErrorLine:
    label: str
    message: str
    href: str


def lines_of(form: Any) -> list[ErrorLine]:
    lines: list[ErrorLine] = []
    if hasattr(form, "forms"):  # a formset: its own errors, then those of each form
        lines += [ErrorLine("", str(message), "") for message in form.non_form_errors()]
        for sub_form in form.forms:
            lines += lines_of(sub_form)
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


def banner_messages(form: Any) -> list[str]:
    """One message per error, led by the label of its field: `Quantity: This field is required.`"""
    return [
        f"{line.label}: {line.message}" if line.label else line.message for line in lines_of(form)
    ]
