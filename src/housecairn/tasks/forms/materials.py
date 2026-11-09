"""The materials of a task in the task form, and the small form of the task page."""

from decimal import Decimal
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from housecairn.stock.models import Article
from housecairn.tasks import materials as material_services

MIN_QUANTITY = Decimal("0.01")


class ArticleChoiceField(forms.ModelChoiceField[Article]):
    """A stock item of the home, by its name."""

    def label_from_instance(self, obj: Article) -> str:
        return obj.name


def _quantity() -> forms.DecimalField:
    return forms.DecimalField(
        label=_("Quantity"),
        min_value=MIN_QUANTITY,
        max_digits=10,
        decimal_places=2,
        required=False,
    )


class MaterialLineForm(forms.Form):
    """One line: a stock item and the quantity the task needs. An empty line is ignored."""

    article = ArticleChoiceField(
        label=_("Stock item"), queryset=Article.objects.none(), required=False, empty_label="—"
    )
    quantity = _quantity()

    def __init__(self, *args: Any, articles: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["article"].queryset = articles  # type: ignore[attr-defined]

    def clean(self) -> dict[str, Any]:
        data: dict[str, Any] = super().clean() or {}
        article, quantity = data.get("article"), data.get("quantity")
        if article is not None and quantity is None and "quantity" not in self.errors:
            self.add_error("quantity", _("Give the quantity."))
        if article is None and quantity is not None and "article" not in self.errors:
            self.add_error("article", _("Choose the stock item."))
        return data


class BaseMaterialFormSet(forms.BaseFormSet[MaterialLineForm]):
    def clean(self) -> None:
        super().clean()
        if any(self.errors):
            return
        chosen = [f.cleaned_data["article"] for f in self.forms if f.cleaned_data.get("article")]
        if len(chosen) != len(set(chosen)):
            raise forms.ValidationError(_("A stock item is listed once for a task."))

    @property
    def is_open(self) -> bool:
        """Show the section unfolded: there are lines already, or something to correct."""
        failed = self.is_bound and (bool(self.non_form_errors()) or any(self.errors))
        return bool(self.initial_form_count()) or failed

    def lines(self) -> list[tuple[Article, Decimal]]:
        """The lines filled in, once the formset is valid."""
        return [
            (f.cleaned_data["article"], f.cleaned_data["quantity"])
            for f in self.forms
            if f.cleaned_data.get("article")
        ]


MaterialFormSet = forms.formset_factory(
    MaterialLineForm,
    formset=BaseMaterialFormSet,
    extra=2,
    max_num=material_services.MAX_MATERIALS_PER_TASK,
    absolute_max=material_services.MAX_MATERIALS_PER_TASK,
)


class MaterialSaveForm(forms.Form):
    """The small form of the task page: add a stock item, or change the quantity of one."""

    article = ArticleChoiceField(
        label=_("Stock item"), queryset=Article.objects.none(), empty_label="—"
    )
    quantity = forms.DecimalField(
        label=_("Quantity"), min_value=MIN_QUANTITY, max_digits=10, decimal_places=2
    )

    def __init__(self, *args: Any, articles: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["article"].queryset = articles  # type: ignore[attr-defined]
