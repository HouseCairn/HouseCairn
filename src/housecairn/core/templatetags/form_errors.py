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

from typing import Any

from django import template

from housecairn.core.form_errors import ErrorLine, lines_of

register = template.Library()


@register.simple_tag
def error_lines(*forms: Any) -> list[ErrorLine]:
    """The lines of the summary: those of each form, formsets included, in order."""
    return [line for form in forms if form not in (None, "") for line in lines_of(form)]
