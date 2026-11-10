"""The `money` filter: one way to write an amount, in every language (docs/adr/0054)."""

from decimal import Decimal

import pytest
from django.utils import translation

from housecairn.core.templatetags.money import money


def shown(amount: str | None, currency: str, language: str) -> str:
    with translation.override(language):
        return money(None if amount is None else Decimal(amount), currency)


class TestMoney:
    def test_french_puts_the_symbol_after_the_number(self) -> None:
        assert shown("1250.50", "EUR", "fr") == "1\u202f250,50\u00a0€"

    def test_english_puts_the_symbol_before_the_number(self) -> None:
        assert shown("1250.50", "EUR", "en") == "€1,250.50"

    def test_the_symbol_is_the_one_the_language_gives(self) -> None:
        assert shown("3", "USD", "en") == "$3.00"
        assert shown("3", "USD", "fr") == "3,00\u00a0$US"

    def test_a_currency_without_a_symbol_in_the_language_shows_its_code(self) -> None:
        assert shown("1250.50", "SEK", "fr") == "1\u202f250,50\u00a0SEK"
        assert shown("1250.50", "SEK", "en") == "SEK\u00a01,250.50"

    def test_an_unknown_code_is_shown_as_it_is(self) -> None:
        assert shown("5", "ZZZ", "fr") == "5,00\u00a0ZZZ"

    def test_a_negative_amount_keeps_its_sign(self) -> None:
        assert shown("-1250.50", "EUR", "fr") == "-1\u202f250,50\u00a0€"
        assert shown("-1250.50", "EUR", "en") == "-€1,250.50"

    @pytest.mark.parametrize("currency", ["EUR", "JPY", "CHF"])
    def test_two_decimals_whatever_the_currency(self, currency: str) -> None:
        assert shown("7.5", currency, "en").endswith("7.50")

    def test_the_amount_is_exact(self) -> None:
        assert shown("9999999999.99", "EUR", "en") == "€9,999,999,999.99"

    def test_no_amount_shows_nothing(self) -> None:
        assert shown(None, "EUR", "en") == ""

    def test_no_currency_shows_the_number_alone(self) -> None:
        assert shown("1250.5", "", "en") == "1,250.50"

    def test_a_language_babel_does_not_know_falls_back_to_english(self) -> None:
        assert shown("1250.50", "EUR", "xx") == "€1,250.50"
