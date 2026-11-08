"""Business rules of stock items, suppliers and movements (docs/adr/0002, 0038).

Web views and API views call these functions; neither holds rules of its own.
Reading is limited to the user's homes by the views (`housecairn.homes.scoping`);
writing is checked here, by role: owners and members write, read-only reads.
"""

import datetime
from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.db import models, transaction
from django.db.models.functions import Coalesce
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext as _

from housecairn.accounts.models import User
from housecairn.homes import quotas
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.rooms import conf, images
from housecairn.rooms.models import Item
from housecairn.stock.models import Article, Movement, MovementKind, Supplier

AnyUser = User | AnonymousUser

ARTICLE_FIELDS = frozenset(
    {
        "name",
        "manufacturer_reference",
        "dimensions",
        "storage_location",
        "unit",
        "threshold",
        "notes",
    }
)
SUPPLIER_FIELDS = frozenset({"name", "reference", "url", "last_price"})
_ZERO = Decimal("0")


def _require_write(actor: AnyUser, home: Home) -> None:
    if not home_services.can_write(actor, home):
        raise PermissionDenied


def _apply(instance: models.Model, allowed: frozenset[str], changes: dict[str, Any]) -> None:
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Cannot change: {', '.join(sorted(unknown))}")
    for field, value in changes.items():
        setattr(instance, field, value)


def plain(quantity: Decimal) -> str:
    """The quantity without trailing zeros: `3`, `0.5`."""
    text = f"{quantity:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


# ---------- reading ----------


def articles_of(home: Home) -> models.QuerySet[Article]:
    """Articles of the home, each with `quantity`: the sum of its movements."""
    total = (
        Movement.objects.filter(article=models.OuterRef("pk"))
        .order_by()
        .values("article")
        .annotate(total=models.Sum("delta"))
        .values("total")
    )
    decimal: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=12, decimal_places=2
    )
    articles: models.QuerySet[Article] = Article.objects.filter(home=home).annotate(
        quantity=Coalesce(
            models.Subquery(total, output_field=decimal),
            models.Value(_ZERO, output_field=decimal),
        )
    )
    return articles


def search_articles(
    home: Home, query: str = "", *, low: bool = False, item: UUID | None = None
) -> models.QuerySet[Article]:
    """Articles whose name, manufacturer reference or supplier matches `query`.

    `low` keeps those at or below their threshold; `item` those compatible with an item.
    """
    articles = articles_of(home)
    query = query.strip()
    if query:
        suppliers = Supplier.objects.filter(article=models.OuterRef("pk")).filter(
            models.Q(name__icontains=query) | models.Q(reference__icontains=query)
        )
        articles = articles.filter(
            models.Q(name__icontains=query)
            | models.Q(manufacturer_reference__icontains=query)
            | models.Exists(suppliers)
        )
    if low:
        articles = articles.filter(
            threshold__isnull=False,
            quantity__lte=models.F("threshold"),  # type: ignore[misc]
        )
    if item is not None:
        articles = articles.filter(compatible_items=item)
    return articles


def is_low(article: Article, quantity: Decimal) -> bool:
    return article.threshold is not None and quantity <= article.threshold


def quantity_of(article: Article) -> Decimal:
    """The stock of the article: the sum of the effects of its movements."""
    total: Decimal | None = Movement.objects.filter(article=article).aggregate(
        total=models.Sum("delta")
    )["total"]
    return total if total is not None else _ZERO


def suppliers_of(home: Home) -> models.QuerySet[Supplier]:
    return Supplier.objects.filter(home=home).select_related("article")


def movements_of(home: Home) -> models.QuerySet[Movement]:
    return Movement.objects.filter(home=home).select_related("article")


# ---------- label photo ----------


def _read_upload(upload: UploadedFile) -> bytes:
    limit = conf.photo_max_bytes()
    too_large = ValidationError(
        _("This file is too large: the limit is %(limit)s."),
        params={"limit": filesizeformat(limit)},
    )
    if upload.size is not None and upload.size > limit:
        raise too_large
    data: bytes = upload.read(limit + 1)
    if len(data) > limit:
        raise too_large
    if not data:
        raise ValidationError(_("This file is empty."))
    return data


def _check_label(upload: UploadedFile) -> images.ProcessedPhoto:
    """Decode and re-encode the upload: nothing of the file sent survives (docs/adr/0030)."""
    try:
        return images.process(_read_upload(upload))
    except ValidationError as exc:
        raise ValidationError({"label": exc.messages}) from exc


def _clear_label(article: Article) -> None:
    if article.label:
        article.label.delete(save=False)
    article.label = ""
    article.label_content_type = ""


def _write_label(article: Article, processed: images.ProcessedPhoto) -> None:
    # A new label replaces the old one: one more file only when there was none.
    try:
        with quotas.room_for(
            article.home, size=len(processed.data), new_files=0 if article.label else 1
        ):
            _clear_label(article)
            article.label.save(processed.extension, ContentFile(processed.data), save=False)
    except ValidationError as exc:
        raise ValidationError({"label": exc.messages}) from exc
    article.label_content_type = processed.content_type


# ---------- articles ----------


def _check_items(home: Home, items: Iterable[Item]) -> list[Item]:
    chosen = list(items)
    if any(item.home_id != home.id for item in chosen):
        raise ValidationError({"compatible_items": _("This item is not in this home.")})
    return chosen


@transaction.atomic
def create_article(
    actor: AnyUser,
    home: Home,
    *,
    compatible_items: Iterable[Item] = (),
    label: UploadedFile | None = None,
    **fields: Any,
) -> Article:
    _require_write(actor, home)
    article = Article(home=home)
    _apply(article, ARTICLE_FIELDS, fields)
    article.full_clean(exclude=["label"])
    items = _check_items(home, compatible_items)
    processed = _check_label(label) if label is not None else None
    if processed is not None:
        _write_label(article, processed)
    article.save()
    article.compatible_items.set(items)
    return article


@transaction.atomic
def update_article(
    actor: AnyUser,
    article: Article,
    *,
    compatible_items: Iterable[Item] | None = None,
    label: UploadedFile | None = None,
    clear_label: bool = False,
    **changes: Any,
) -> Article:
    """Change the article; `label` replaces the photo, `clear_label` removes it."""
    _require_write(actor, article.home)
    _apply(article, ARTICLE_FIELDS, changes)
    article.full_clean(exclude=["label"])
    items = None if compatible_items is None else _check_items(article.home, compatible_items)
    processed = _check_label(label) if label is not None else None
    if processed is not None:
        _write_label(article, processed)
    elif clear_label:
        _clear_label(article)
    article.save()
    if items is not None:
        article.compatible_items.set(items)
    return article


@transaction.atomic
def delete_article(actor: AnyUser, article: Article) -> None:
    """Soft-delete the article with its suppliers and movements."""
    _require_write(actor, article.home)
    Supplier.objects.filter(article=article).soft_delete()  # type: ignore[attr-defined]
    Movement.objects.filter(article=article).soft_delete()  # type: ignore[attr-defined]
    article.soft_delete()


# ---------- suppliers ----------


def create_supplier(actor: AnyUser, article: Article, **fields: Any) -> Supplier:
    _require_write(actor, article.home)
    supplier = Supplier(home=article.home, article=article)
    _apply(supplier, SUPPLIER_FIELDS, fields)
    supplier.full_clean()
    supplier.save()
    return supplier


def update_supplier(actor: AnyUser, supplier: Supplier, **changes: Any) -> Supplier:
    _require_write(actor, supplier.home)
    _apply(supplier, SUPPLIER_FIELDS, changes)
    supplier.full_clean()
    supplier.save()
    return supplier


def delete_supplier(actor: AnyUser, supplier: Supplier) -> None:
    _require_write(actor, supplier.home)
    supplier.soft_delete()


# ---------- movements ----------


@transaction.atomic
def record_movement(
    actor: AnyUser,
    article: Article,
    *,
    kind: str,
    quantity: Decimal,
    occurred_on: datetime.date | None = None,
    note: str = "",
) -> Movement:
    """Add a line to the ledger of the article.

    An entry adds `quantity`, an exit takes it (never more than there is), an inventory
    states the quantity counted and records the difference with the stock until then.
    """
    _require_write(actor, article.home)
    if kind not in MovementKind.values:
        raise ValidationError({"kind": _("Choose entry, exit or inventory.")})
    if kind != MovementKind.INVENTORY and quantity <= _ZERO:
        raise ValidationError({"quantity": _("The quantity must be more than zero.")})
    # Lock the article so that two movements at once cannot both read the same stock.
    Article.objects.select_for_update().get(pk=article.pk)
    current = quantity_of(article)
    if kind == MovementKind.ENTRY:
        delta = quantity
    elif kind == MovementKind.EXIT:
        if quantity > current:
            raise ValidationError(
                {"quantity": _("Only %(available)s in stock.") % {"available": plain(current)}}
            )
        delta = -quantity
    else:
        delta = quantity - current
    movement = Movement(
        home=article.home, article=article, kind=kind, quantity=quantity, delta=delta, note=note
    )
    if occurred_on is not None:
        movement.occurred_on = occurred_on
    movement.full_clean()
    movement.save()
    return movement
