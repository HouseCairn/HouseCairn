"""Form fields shared by several areas of the application."""

from typing import Any

from django import forms

_MONEY = {"inputmode": "decimal", "autocomplete": "off"}
# Spaces that group thousands: the space, the no-break space and the narrow ones of French.
_GROUPING = dict.fromkeys(map(ord, " \u00a0\u2009\u202f"))


class MoneyField(forms.DecimalField):
    """An amount typed the way the person writes it: `1250.50` in English, `1 250,50` in French.

    The decimal mark follows the language (`localize`); the spaces that group thousands are
    dropped here, since Django only drops the separator of the language when the instance
    asks for thousand separators. Two decimals at most, as the model keeps; a scientific
    notation passes only while it stays within the digits of an amount.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("widget", forms.TextInput(attrs=_MONEY))
        super().__init__(max_digits=12, decimal_places=2, min_value=0, localize=True, **kwargs)

    def to_python(self, value: Any) -> Any:
        if isinstance(value, str):
            value = value.translate(_GROUPING)
        return super().to_python(value)
