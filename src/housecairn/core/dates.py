"""The one way a date is written on a screen (docs/adr/0068).

Django's own formats mix styles: in English its long date format gives `Nov. 8, 2026` while
its short one gives `02/08/2027`, which reads as 2 August or 8 February depending on the
reader. Every date shown by the application goes through these functions (the template filters
of `core.templatetags.dates` call them): one format per language, the one of the Unicode CLDR
that Babel carries (as for the amounts, ADR 0054), with the month always in letters and never
the day and the month in digits: `Nov 8, 2026` in English, `8 nov. 2026` in French.
"""

import datetime

from babel import Locale, UnknownLocaleError
from babel.dates import format_skeleton, format_time
from django.utils.translation import get_language


def current_locale() -> Locale:
    """The locale of the language being served; English when Babel does not know it."""
    try:
        return Locale.parse(get_language() or "en", sep="-")
    except (UnknownLocaleError, ValueError):
        return Locale.parse("en")


def day(value: datetime.date | None) -> str:
    """A date with its year: `Nov 8, 2026` / `8 nov. 2026`. Empty for no value."""
    if value is None:
        return ""
    return format_skeleton("yMMMd", value, locale=current_locale())


def moment(value: datetime.datetime | None) -> str:
    """A date and the time: `Nov 8, 2026, 2:30 PM` / `8 nov. 2026, 14:30`."""
    if value is None:
        return ""
    locale = current_locale()
    date = format_skeleton("yMMMd", value, locale=locale)
    return f"{date}, {format_time(value, 'short', locale=locale)}"


def month_day(value: datetime.date | None) -> str:
    """A date without its year, when the year is known: `Nov 8` / `8 nov.`."""
    if value is None:
        return ""
    return format_skeleton("MMMd", value, locale=current_locale())


def weekday_day(value: datetime.date | None) -> str:
    """A date with its weekday, without the year: `Sun, Nov 8` / `dim. 8 nov.`."""
    if value is None:
        return ""
    return format_skeleton("MMMEd", value, locale=current_locale())
