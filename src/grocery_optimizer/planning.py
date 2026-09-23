"""High-level "plan my trip": database prices + shopping list -> optimizer result."""

from __future__ import annotations

import csv
import io

from .db import PriceDB
from .optimizer import ListItem, OptimizationResult, optimize
from .pricing import current_prices, price_table


def read_shopping_list(text: str) -> list[ListItem]:
    """CSV with columns `product,quantity` (quantity in the product's unit)."""
    reader = csv.DictReader(io.StringIO(text))
    items = []
    for row in reader:
        if not row.get("product"):
            continue
        items.append(ListItem(row["product"].strip(), float(row["quantity"])))
    return items


def plan_trip(
    db: PriceDB,
    items: list[ListItem],
    stores: list[str] | None = None,
    trip_cost: float | dict[str, float] = 0.0,
    max_stores: int | None = None,
    price_method: str = "weighted",
) -> OptimizationResult:
    prices = price_table(current_prices(db.observations(), method=price_method))
    stores = stores if stores is not None else db.store_names()
    return optimize(items, stores, prices, trip_cost=trip_cost, max_stores=max_stores)
