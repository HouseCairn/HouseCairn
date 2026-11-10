"""Tags of the return rule (core/navigation.py, docs/developer/design-guide.md).

- `{% back_link default %}` or `{% back_link default label %}`: the back link of a page.
  It leads to the safe `next` of the request, named after its route, else to `default`,
  named by `label` or by the route of `default`. A link back to More is shown on a phone
  only: on a computer the column already holds More. On a computer the tag also draws the
  breadcrumbs of the page, and the back link stays only on a form or when the origin is
  not the parent.
- `{% back_href default %}` (or `as name`): the same address, for Cancel.
- `{% url_with_next 'tasks:create' home_id=home.id q_item=item.id %}`: the address of a
  route with `next=<this page>`; a keyword prefixed with `q_` goes to the query.
- `{% next_field %}`: the hidden field that keeps a safe `next` through a form.
"""

from typing import Any

from django import template
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import format_html
from django.utils.http import urlencode
from django.utils.safestring import SafeString

from housecairn.core import navigation

register = template.Library()


def _request(context: template.Context) -> HttpRequest:
    request: HttpRequest = context["request"]
    return request


@register.simple_tag(takes_context=True)
def back_link(context: template.Context, default: str, label: Any = None) -> SafeString:
    request = _request(context)
    text = str(label) if label else None
    link = navigation.back_link(request, default, text)
    crumbs = navigation.breadcrumbs(request, default, text)
    # On a computer the breadcrumbs already lead to the parent: the link stays for a form,
    # or when the origin is not the parent (a room opened from the budget).
    covered = bool(crumbs) and link.url == default and not navigation.is_form(request)
    return SafeString(
        (render_to_string("components/breadcrumbs.html", {"crumbs": crumbs}) if crumbs else "")
        + render_to_string(
            "components/back_link.html",
            {"link": link, "phone_only": link.route == "more" or covered},
        )
    )


@register.simple_tag(takes_context=True)
def back_href(context: template.Context, default: str) -> str:
    return navigation.back_url(_request(context), default)


@register.simple_tag(takes_context=True)
def url_with_next(context: template.Context, viewname: str, *args: Any, **kwargs: Any) -> str:
    query = [(key[2:], value) for key, value in kwargs.items() if key.startswith("q_")]
    route_kwargs = {key: value for key, value in kwargs.items() if not key.startswith("q_")}
    url = reverse(viewname, args=args or None, kwargs=route_kwargs or None)
    query = [(key, value) for key, value in query if value not in (None, "")]
    if query:
        url = f"{url}?{urlencode(query)}"
    return navigation.with_next(url, navigation.current_path(_request(context)))


@register.simple_tag(takes_context=True)
def next_field(context: template.Context) -> SafeString:
    target = navigation.safe_next(_request(context))
    if not target:
        return SafeString("")
    return format_html('<input type="hidden" name="next" value="{}">', target)
