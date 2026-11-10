"""The one way an amount is written on a screen (docs/adr/0054)."""

import re
from decimal import Decimal

from babel import Locale, UnknownLocaleError
from babel.numbers import format_currency
from django import template
from django.utils.formats import number_format
from django.utils.translation import get_language

register = template.Library()

# A symbol made of letters ("CHF", "SEK", "F CFA") must not touch the digits: CLDR puts a
# no-break space there, which Babel leaves out when the pattern has none.
_LETTER_THEN_DIGIT = re.compile(r"([^\W\d_])(?=\d)")


def _locale() -> Locale:
    """The locale of the language being served; English when Babel does not know it."""
    try:
        return Locale.parse(get_language() or "en", sep="-")
    except (UnknownLocaleError, ValueError):
        return Locale.parse("en")


@register.filter
def money(amount: Decimal | None, currency: str = "") -> str:
    """An amount as people read it: `1 250,50 €` or `€1,250.50`, exact (never a float).

    Always two decimals, whatever the currency, as the fields of the application accept.
    The symbol is the one the language gives to the currency, else its ISO 4217 code.
    Without a currency, the number alone.
    """
    if amount is None:
        return ""
    if not currency:
        return number_format(amount, decimal_pos=2, use_l10n=True, force_grouping=True)
    text = format_currency(
        amount, currency.upper(), locale=_locale(), currency_digits=False, decimal_quantization=True
    )
    return _LETTER_THEN_DIGIT.sub("\\1\u00a0", text)
