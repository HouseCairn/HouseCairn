"""`{% instance_name %}`: the name of the instance, in every template (docs/adr/0042).

A built-in tag, so that pages, error pages and emails need no `{% load %}` and no
context processor. It returns the text as is: where autoescaping is on (pages, HTML
emails) Django escapes it like any variable; plain-text emails show it unchanged.
"""

from django import template

from housecairn.instance.config import instance_name as _instance_name

register = template.Library()


@register.simple_tag
def instance_name() -> str:
    return _instance_name()
