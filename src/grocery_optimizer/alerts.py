"""Price-drop alerts for watched products.

The user watches a product with a target price, e.g. "milk (whole) at
$3.00/gal". A store triggers an alert when its *latest* observed price for
that product is at or below the target. We compare the latest price (not the
recency-weighted one) because an alert is about "what does it cost right
now", and a sale should show up immediately.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .db import Observation


@dataclass(frozen=True)
class PriceAlert:
    product: str
    store: str
    price: float  # latest price at this store, $ per product unit
    target_price: float
    observed_date: dt.date
    previous_price: float | None  # the observation before the latest one, if any


def latest_by_store(observations: list[Observation], product: str) -> dict[str, list[Observation]]:
    """store -> this product's observations at that store, oldest first."""
    by_store: dict[str, list[Observation]] = {}
    for obs in sorted((o for o in observations if o.product == product),
                      key=lambda o: o.observed_date):
        by_store.setdefault(obs.store, []).append(obs)
    return by_store


def price_alerts(watchlist: dict[str, float], observations: list[Observation]) -> list[PriceAlert]:
    """Every (watched product, store) whose latest price is at or below the target.

    Sorted by product, then cheapest store first.
    """
    alerts = []
    for product, target in watchlist.items():
        for store, history in latest_by_store(observations, product).items():
            latest = history[-1]
            if latest.unit_price <= target:
                previous = history[-2].unit_price if len(history) > 1 else None
                alerts.append(PriceAlert(product, store, round(latest.unit_price, 4), target,
                                         latest.observed_date, previous))
    return sorted(alerts, key=lambda a: (a.product, a.price))
