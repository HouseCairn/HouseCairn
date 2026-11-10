"""Stock items, suppliers and movements in the export of their home (docs/adr/0038, 0048).

The photo of a label goes into `files/stock/`, already stripped of its metadata at upload
(docs/adr/0030). The quantity in stock is not a field: it is the sum of the movements.
"""

from housecairn.homes import exports
from housecairn.stock.models import Article, Movement, Supplier


def register() -> None:
    exports.register(
        "stock",
        exports.Section(
            "stock_items",
            Article,
            files=(exports.FileSpec("label", "stock", content_type="label_content_type"),),
        ),
        exports.Section("stock_suppliers", Supplier),
        exports.Section("stock_movements", Movement),
    )
