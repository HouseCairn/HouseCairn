"""Stock items, their suppliers and their movements (docs/adr/0038)."""

from decimal import Decimal
from typing import Any

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from housecairn.homes.models import HomeOwnedModel
from housecairn.rooms.models import Item, WebUrlField, notes_field
from housecairn.stock.storage import stock_storage

NON_NEGATIVE = MinValueValidator(Decimal("0"))


def quantity_field(label: Any, **options: Any) -> models.DecimalField[Decimal, Decimal]:
    return models.DecimalField(label, max_digits=10, decimal_places=2, **options)


def label_path(article: "Article", filename: str) -> str:
    """Storage name: home and article identifiers only, never a name chosen by the sender."""
    return f"{article.home_id}/{article.id}{filename}"


class Article(HomeOwnedModel):
    """Something kept in stock: a spare part, a tin of paint, a box of screws."""

    name = models.CharField(_("name"), max_length=120)
    manufacturer_reference = models.CharField(
        _("manufacturer reference"), max_length=120, blank=True
    )
    dimensions = models.CharField(_("dimensions"), max_length=120, blank=True)
    storage_location = models.CharField(
        _("storage location"),
        max_length=200,
        blank=True,
        help_text=_("For example: garage, second shelf."),
    )
    unit = models.CharField(
        _("unit"),
        max_length=24,
        blank=True,
        help_text=_("For example: pieces, litres, metres."),
    )
    threshold = quantity_field(
        _("threshold"),
        null=True,
        blank=True,
        validators=[NON_NEGATIVE],
        help_text=_("The stock is flagged when it falls to this quantity or below."),
    )
    compatible_items = models.ManyToManyField(
        Item, blank=True, related_name="+", verbose_name=_("compatible items")
    )
    notes = notes_field(_("notes"))
    # Photo of the label, re-encoded on upload (housecairn.rooms.images).
    label = models.FileField(
        storage=stock_storage, upload_to=label_path, max_length=200, editable=False, blank=True
    )
    label_content_type = models.CharField(max_length=32, editable=False, blank=True)

    class Meta:
        verbose_name = _("stock item")
        verbose_name_plural = _("stock items")
        ordering = ["name", "created_at", "id"]
        indexes = [models.Index(fields=["home", "name"], name="article_home_name")]

    def __str__(self) -> str:
        return self.name

    @property
    def unit_label(self) -> str:
        return self.unit


class Supplier(HomeOwnedModel):
    """Where an article is bought; an article has one or more."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="suppliers")
    name = models.CharField(_("name"), max_length=120)
    reference = models.CharField(_("supplier reference"), max_length=120, blank=True)
    url = WebUrlField(_("purchase link"), max_length=500, blank=True)
    last_price = quantity_field(
        _("last price paid"), null=True, blank=True, validators=[NON_NEGATIVE]
    )

    class Meta:
        verbose_name = _("supplier")
        verbose_name_plural = _("suppliers")
        ordering = ["name", "created_at", "id"]

    def __str__(self) -> str:
        return self.name


class MovementKind(models.TextChoices):
    ENTRY = "entry", _("Entry")
    EXIT = "exit", _("Exit")
    INVENTORY = "inventory", _("Inventory")


class Movement(HomeOwnedModel):
    """A line of the stock ledger. Never changed: a mistake is corrected by a new line.

    `quantity` is what the person typed: the amount added or taken, or, for an
    inventory, the quantity counted. `delta` is its effect on the stock, worked
    out once when the line is written; the stock of an article is the sum of its
    deltas and is stored nowhere else.
    """

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField(_("type"), max_length=16, choices=MovementKind.choices)
    quantity = quantity_field(_("quantity"), validators=[NON_NEGATIVE])
    delta = quantity_field(_("change"), editable=False)
    occurred_on = models.DateField(_("date"), default=timezone.localdate)
    note = models.CharField(_("note"), max_length=200, blank=True)
    # The occurrence of a task whose closing (or taking back) wrote this line (docs/adr/0046).
    occurrence = models.ForeignKey(
        "tasks.Occurrence",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = _("movement")
        verbose_name_plural = _("movements")
        ordering = ["-occurred_on", "-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind="inventory") | models.Q(quantity__gt=0),
                name="movement_quantity_positive",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.quantity}"
