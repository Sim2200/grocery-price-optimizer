"""Turn price observations into one current price per (product, store).

Two strategies:

- "latest":   the most recent observation (ties on the same day are averaged).
- "weighted": exponentially recency-weighted mean. An observation that is
              `half_life_days` older than the newest one gets half the weight.
              This smooths out one-off sales without letting stale prices
              dominate.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import datetime as dt

from .config import PRICE_HALF_LIFE_DAYS
from .db import Observation

PriceKey = tuple[str, str]  # (product, store)


@dataclass(frozen=True)
class PriceEstimate:
    price: float
    n_observations: int
    last_seen: dt.date


def recency_weight(age_days: float, half_life_days: float) -> float:
    return 0.5 ** (age_days / half_life_days)


def current_prices(
    observations: list[Observation],
    method: str = "weighted",
    half_life_days: float = PRICE_HALF_LIFE_DAYS,
) -> dict[PriceKey, PriceEstimate]:
    if method not in ("latest", "weighted"):
        raise ValueError("method must be 'latest' or 'weighted'")

    grouped: dict[PriceKey, list[Observation]] = defaultdict(list)
    for obs in observations:
        grouped[(obs.product, obs.store)].append(obs)

    estimates: dict[PriceKey, PriceEstimate] = {}
    for key, group in grouped.items():
        newest = max(o.observed_date for o in group)
        if method == "latest":
            same_day = [o.unit_price for o in group if o.observed_date == newest]
            price = sum(same_day) / len(same_day)
        else:
            weights = [recency_weight((newest - o.observed_date).days, half_life_days) for o in group]
            price = sum(w * o.unit_price for w, o in zip(weights, group)) / sum(weights)
        estimates[key] = PriceEstimate(round(price, 4), len(group), newest)
    return estimates


def price_table(estimates: dict[PriceKey, PriceEstimate]) -> dict[PriceKey, float]:
    """Plain {(product, store): price} mapping, the optimizer's input format."""
    return {key: est.price for key, est in estimates.items()}
