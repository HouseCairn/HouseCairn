"""The one way an amount is written on a screen (docs/adr/0054)."""

import re
from decimal import Decimal, InvalidOperation

from babel.numbers import format_currency
from django import template
from django.utils.formats import number_format
from django.utils.html import conditional_escape

from housecairn.core.dates import current_locale

register = template.Library()

# A symbol made of letters ("CHF", "SEK", "F CFA") must not touch the digits: CLDR puts a
# no-break space there, which Babel leaves out when the pattern has none.
_LETTER_THEN_DIGIT = re.compile(r"([^\W\d_])(?=\d)")


def _number(amount: object) -> Decimal | None:
    """The value as an exact decimal, or None when it is no finite number."""
    try:
        number = amount if isinstance(amount, Decimal) else Decimal(str(amount).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _plain(number: Decimal) -> str:
    """The number alone, grouped and with two decimals."""
    return number_format(number, decimal_pos=2, use_l10n=True, force_grouping=True)


@register.filter
def money(amount: Decimal | str | None, currency: str = "") -> str:
    """An amount as people read it: `1 250,50 €` or `€1,250.50`, exact (never a float).

    Always two decimals, whatever the currency, as the fields of the application accept.
    The symbol is the one the language gives to the currency, else its ISO 4217 code.
    Without a currency, the number alone. Never raises: an empty value (a template variable
    that is missing) shows nothing, and a value Babel cannot format (not a number, more
    than 28 significant digits) falls back to the number and the ISO code.
    """
    if amount is None or amount == "":
        return ""
    number = _number(amount)
    if number is None:
        return conditional_escape(str(amount))
    if not currency:
        return _plain(number)
    try:
        text = format_currency(
            number,
            currency.upper(),
            locale=current_locale(),
            currency_digits=False,
            decimal_quantization=True,
        )
    except (InvalidOperation, TypeError, ValueError):
        return f"{_plain(number)}\u00a0{currency.upper()}"
    return _LETTER_THEN_DIGIT.sub("\\1\u00a0", text)
