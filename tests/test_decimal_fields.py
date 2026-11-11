"""Decimal fields: the mark follows the language, and a refused comma says what is expected."""

import html
import importlib
import pkgutil
from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from django import forms
from django.test import Client
from django.urls import reverse
from django.utils import translation

import housecairn
from housecairn.core.forms import DecimalMarkField, MoneyField, QuantityField
from housecairn.homes.models import Home
from housecairn.projects import forms as project_forms
from housecairn.stock import forms as stock_forms
from housecairn.stock import services as stock_services
from housecairn.stock.models import Article, Movement
from housecairn.tasks import forms as task_forms
from housecairn.tasks.forms import materials as material_forms
from housecairn.tasks.forms import occurrence as occurrence_forms

pytest_plugins = ("tests.rooms_fixtures", "tests.stock_fixtures")

HINT_EN = "Enter a number with a point as the decimal mark, for example 12.5."
HINT_FR = "Saisissez un nombre avec un point comme séparateur décimal, par exemple 12.5."


def message(field: forms.Field, value: str) -> str | None:
    """The first error of a value typed in the field, None when it is accepted."""
    try:
        field.clean(value)
    except forms.ValidationError as error:
        return str(error.messages[0])
    return None


FIELDS: list[tuple[str, forms.Field]] = [
    ("quantity", QuantityField()),
    ("money", MoneyField()),
    ("movement", stock_forms.MovementForm.base_fields["quantity"]),
    ("threshold", stock_forms.ArticleForm.base_fields["threshold"]),
    ("last price", stock_forms.SupplierForm.base_fields["last_price"]),
    ("material line", material_forms.MaterialLineForm.base_fields["quantity"]),
    ("material", material_forms.MaterialSaveForm.base_fields["quantity"]),
    ("project budget", project_forms.ProjectForm.base_fields["budget"]),
    ("budget line", project_forms.LineForm.base_fields["planned"]),
    ("quote", project_forms.QuoteForm.base_fields["amount"]),
    ("envelope", project_forms.EnvelopeForm.base_fields["amount"]),
    ("actual cost", occurrence_forms.CompletionForm.base_fields["actual_cost"]),
    ("task budget", task_forms.TaskForm.base_fields["labour_budget"]),
]


def every_form() -> Iterator[type[forms.BaseForm]]:
    """The forms of the application, found by importing all its modules."""
    for module in pkgutil.walk_packages(housecairn.__path__, "housecairn."):
        if ".migrations" not in module.name and not module.name.endswith(".settings"):
            importlib.import_module(module.name)
    pending = [forms.Form, forms.ModelForm]
    while pending:
        for sub in pending.pop().__subclasses__():
            pending.append(sub)
            if sub.__module__.startswith("housecairn"):
                yield sub


class TestTheComma:
    @pytest.mark.parametrize(("name", "field"), FIELDS, ids=[name for name, _ in FIELDS])
    def test_english_refuses_it_and_says_the_format(self, name: str, field: forms.Field) -> None:
        with translation.override("en"):
            assert message(field, "12,5") == HINT_EN
            assert message(field, "12.5") is None

    @pytest.mark.parametrize(("name", "field"), FIELDS, ids=[name for name, _ in FIELDS])
    def test_french_accepts_it(self, name: str, field: forms.Field) -> None:
        with translation.override("fr"):
            assert message(field, "12,5") is None
            assert field.clean("12,5") == Decimal("12.5")

    def test_every_decimal_field_of_a_form_is_one_of_ours(self) -> None:
        found = list(every_form())
        assert len(found) > 20
        plain = sorted(
            f"{form.__module__}.{form.__name__}.{name}"
            for form in found
            for name, field in form.base_fields.items()  # type: ignore[attr-defined]
            if isinstance(field, forms.DecimalField | forms.FloatField)
            and not isinstance(field, DecimalMarkField)
        )
        assert plain == []

    def test_the_quantity_used_when_a_task_is_done(self) -> None:
        article = SimpleNamespace(name="Filter", unit_label="piece")
        draw = SimpleNamespace(article_id="a1", article=article, wanted=Decimal("2"))
        field = occurrence_forms.CompletionForm(draws=[draw]).fields["used_a1"]  # type: ignore[list-item]
        with translation.override("en"):
            assert message(field, "1,5") == HINT_EN
        with translation.override("fr"):
            assert field.clean("1,5") == Decimal("1.5")

    def test_a_word_still_gets_the_plain_message(self) -> None:
        with translation.override("en"):
            assert message(QuantityField(), "twelve") == "Enter a number."
            assert message(MoneyField(), "1.2.3") == "Enter a number."

    def test_the_box_is_a_text_box_with_the_numeric_keyboard(self) -> None:
        widget = QuantityField().widget
        assert not isinstance(widget, forms.NumberInput)
        assert widget.attrs["inputmode"] == "decimal"

    def test_the_hint_is_translated(self) -> None:
        with translation.override("fr"):
            assert str(QuantityField().error_messages["decimal_point"]) == HINT_FR


@pytest.mark.django_db
@pytest.mark.usefixtures("media_root")
class TestOnTheScreen:
    @staticmethod
    def banner(client: Client, response: Any) -> str:
        page = client.get(response["Location"]).content.decode()
        return html.unescape(page)

    def test_english_shows_the_hint_and_records_nothing(
        self, signed_in: Client, alice_home: Home, article: Article
    ) -> None:
        address = reverse(
            "stock:movement-add", kwargs={"home_id": alice_home.id, "article_id": article.id}
        )
        response = signed_in.post(
            address, {"kind": "entry", "quantity": "12,5"}, HTTP_ACCEPT_LANGUAGE="en"
        )
        assert response.status_code == 302
        assert HINT_EN in self.banner(signed_in, response)
        assert Movement.objects.count() == 0

    def test_french_records_the_amount(
        self, signed_in: Client, alice_home: Home, article: Article
    ) -> None:
        address = reverse(
            "stock:movement-add", kwargs={"home_id": alice_home.id, "article_id": article.id}
        )
        before = stock_services.quantity_of(article)
        response = signed_in.post(
            address, {"kind": "entry", "quantity": "12,5"}, HTTP_ACCEPT_LANGUAGE="fr"
        )
        assert response.status_code == 302
        assert stock_services.quantity_of(article) == before + Decimal("12.5")
