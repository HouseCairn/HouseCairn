"""Stock items, suppliers and movements are part of the export of their home (docs/adr/0023, 0038).

Plain objects with identifiers, dates and amounts as text. The photo of a label goes into
`files/stock/`, already stripped of its metadata at upload (docs/adr/0030).
"""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.core.exceptions import SuspiciousFileOperation
from django.db.models import Prefetch

from housecairn.homes import exports
from housecairn.homes.models import Home
from housecairn.rooms.files import EXTENSIONS
from housecairn.rooms.models import Item, Room
from housecairn.stock import services
from housecairn.stock.models import Article, Movement, Supplier
from housecairn.stock.storage import stock_storage

CENT = Decimal("0.01")


def _archive_name(article: Article) -> str:
    return f"stock/{article.id}{EXTENSIONS.get(article.label_content_type, '')}"


def _stored_file(article: Article) -> Path | None:
    """The label photo on disk, if it is there and inside the folder of its own home."""
    if not article.label:
        return None
    try:
        path = Path(stock_storage.path(article.label.name)).resolve()
    except (SuspiciousFileOperation, ValueError, OSError):
        return None
    folder = (Path(stock_storage.location) / str(article.home_id)).resolve()
    if path.parent != folder or not path.is_file():
        return None
    return path


def _articles(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(a.id),
            "name": a.name,
            "manufacturer_reference": a.manufacturer_reference,
            "dimensions": a.dimensions,
            "storage_location": a.storage_location,
            "unit": a.unit,
            "unit_other": a.unit_other,
            "threshold": str(a.threshold) if a.threshold is not None else None,
            "quantity": str(a.quantity.quantize(CENT)),  # type: ignore[attr-defined]
            "compatible_items": [str(i.pk) for i in a.compatible_items.all()],
            "rooms": [str(r.pk) for r in a.rooms.all()],
            "notes": a.notes,
            "label": f"files/{_archive_name(a)}" if _stored_file(a) else None,
            "created_at": a.created_at.isoformat(),
        }
        for a in services.articles_of(home)
        .order_by("created_at", "id")
        .prefetch_related(
            # One query per relation for all the articles, in the order of the identifiers.
            Prefetch("compatible_items", queryset=Item.objects.order_by("id")),
            Prefetch("rooms", queryset=Room.objects.order_by("id")),
        )
    ]


def _suppliers(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(s.id),
            "article": str(s.article_id),
            "name": s.name,
            "reference": s.reference,
            "url": s.url,
            "last_price": str(s.last_price) if s.last_price is not None else None,
            "created_at": s.created_at.isoformat(),
        }
        for s in Supplier.objects.filter(home=home, article__deleted_at__isnull=True).order_by(
            "created_at", "id"
        )
    ]


def _movements(home: Home) -> list[dict[str, Any]]:
    return [
        {
            "id": str(m.id),
            "article": str(m.article_id),
            "kind": m.kind,
            "quantity": str(m.quantity),
            "delta": str(m.delta),
            "occurred_on": m.occurred_on.isoformat(),
            "note": m.note,
            "occurrence": str(m.occurrence_id) if m.occurrence_id else None,
            "created_at": m.created_at.isoformat(),
        }
        for m in Movement.objects.filter(home=home, article__deleted_at__isnull=True).order_by(
            "created_at", "id"
        )
    ]


def _files(home: Home) -> Iterator[exports.ExportedFile]:
    for article in Article.objects.filter(home=home).order_by("created_at", "id"):
        source = _stored_file(article)
        if source is not None:
            yield exports.ExportedFile(name=_archive_name(article), source=source)


def register() -> None:
    exports.register("stock_items", _articles)
    exports.register("stock_suppliers", _suppliers)
    exports.register("stock_movements", _movements)
    exports.register_files(_files)
