"""`{{ user|person }}`: a person by their name, never by their address (docs/adr/0045)."""

from typing import Any

from django import template

from housecairn.accounts.names import person_name

register = template.Library()
register.filter("person", person_name)


@register.simple_tag
def person(user: Any) -> str:
    return person_name(user)
