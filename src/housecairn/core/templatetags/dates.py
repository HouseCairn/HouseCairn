"""Template filters for dates: `{{ value|day }}`, `|moment`, `|weekday_day` (docs/adr/0068).

They are the only filters that write a date in a template; `core.dates` holds the formats.
`|date:` stays for the machine formats (`Y-m-d` of an input) and the parts of a calendar
(`F Y`, a weekday name), never for a date read as such.
"""

import datetime

from django import template

from housecairn.core import dates

register = template.Library()


@register.filter(expects_localtime=True)
def day(value: datetime.date | None) -> str:
    return dates.day(value or None)


@register.filter(expects_localtime=True)
def moment(value: datetime.datetime | None) -> str:
    return dates.moment(value or None)


@register.filter
def weekday_day(value: datetime.date | None) -> str:
    return dates.weekday_day(value or None)
