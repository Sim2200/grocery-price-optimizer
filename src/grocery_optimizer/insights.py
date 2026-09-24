"""Spending insights from saved receipts.

1. Spend breakdown: how much went to each store, category and month. Spend is
   the sum of line totals (item prices, before receipt-level tax and fees).

2. "What if I had used the planner?" For each past receipt (one trip):
   - the shopping list is that receipt's matched lines, with quantities in
     the product's unit (line_total / comparable price = e.g. 2.1 lb);
   - prices are what we knew *on that date*: the latest observation at each
     store up to and including the receipt date;
   - at the store actually visited we use the prices actually paid, so the
     trip that really happened is one of the optimizer's options and the
     estimated saving can never be negative;
   - actual cost = what was paid for those lines + one trip cost;
     optimal cost = the optimizer's plan (items + its trip costs).
   Unmatched lines and lines without a comparable price are left out.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from .db import Observation
from .optimizer import ListItem, solve_milp
from .pricing import current_prices, price_table


@dataclass(frozen=True)
class TripReplay:
    receipt_id: int
    store: str
    date: dt.date
    actual: float    # paid for the comparable lines + one trip
    optimal: float   # optimizer plan for the same items with prices known that day
    stores_in_plan: list[str]

    @property
    def saved(self) -> float:
        return round(self.actual - self.optimal, 2)


def _totals(pairs) -> list[tuple[str, float]]:
    sums: dict[str, float] = defaultdict(float)
    for key, amount in pairs:
        sums[key] += amount
    return sorted(((k, round(v, 2)) for k, v in sums.items()), key=lambda kv: -kv[1])


def spend_breakdown(lines: list[dict], categories: dict[str, str]) -> dict[str, list[tuple[str, float]]]:
    """Spend by store, by category ("unmatched" for lines with no product) and by month."""
    return {
        "by_store": _totals((li["store"], li["line_total"]) for li in lines),
        "by_category": _totals(
            (categories.get(li["product"], "other") if li["product"] else "unmatched",
             li["line_total"]) for li in lines),
        # Months stay in calendar order rather than by amount.
        "by_month": sorted(_totals(((li["purchase_date"] or "unknown")[:7], li["line_total"])
                                   for li in lines)),
    }


def replay_trips(lines: list[dict], observations: list[Observation],
                 trip_cost: float) -> list[TripReplay]:
    """Re-plan every past receipt with the optimizer (see module docstring)."""
    by_receipt: dict[int, list[dict]] = defaultdict(list)
    for li in lines:
        if li["product"] and li["comparable_price"]:
            by_receipt[li["receipt_id"]].append(li)

    replays = []
    for receipt_id, rlines in sorted(by_receipt.items()):
        store = rlines[0]["store"]
        date = dt.date.fromisoformat(rlines[0]["purchase_date"])
        known = [o for o in observations if o.observed_date <= date]
        prices = price_table(current_prices(known, method="latest"))

        quantities: dict[str, float] = defaultdict(float)
        paid: dict[str, float] = defaultdict(float)
        for li in rlines:
            quantities[li["product"]] += li["line_total"] / li["comparable_price"]
            paid[li["product"]] += li["line_total"]
        for product, qty in quantities.items():
            prices[(product, store)] = paid[product] / qty  # what was actually paid per unit

        items = [ListItem(p, q) for p, q in quantities.items()]
        stores = sorted({s for _, s in prices})
        plan = solve_milp(items, stores, prices, trip_cost, None)
        actual = round(sum(paid.values()) + trip_cost, 2)
        optimal = min(round(plan.total, 2), actual)  # min() only guards against float rounding
        replays.append(TripReplay(receipt_id, store, date, actual, optimal, plan.stores))
    return replays
