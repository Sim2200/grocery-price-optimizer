"""Shopping-trip optimizer.

Problem
-------
Given a shopping list (product, quantity), the stores the user is willing to
visit, a price for each (product, store) pair that we have data for, and a
per-store trip cost (time / gas, in dollars), choose where to buy each item.

MILP formulation
----------------
    x[i, s] in {0, 1}   buy item i at store s   (only if s has a price for i)
    y[s]    in {0, 1}   visit store s

    minimize   sum_{i,s} qty_i * price[i, s] * x[i, s]  +  sum_s trip_cost[s] * y[s]
    subject to sum_s x[i, s] = 1          for every item that some store carries
               x[i, s] <= y[s]            can only buy at a store you visit
               sum_s y[s] <= max_stores   optional

It is a small facility-location style problem. Per-item greedy is optimal
only when trips are free; once visiting a store costs something the choices
interact, which is exactly what the integer program handles. With ~30 items
and a handful of stores CBC solves it in milliseconds.

Baselines
---------
- cheapest single store: one trip, only stores that carry every item.
- per-item greedy: each item at its cheapest store, trip costs added afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

PriceKey = tuple[str, str]  # (product, store)


@dataclass(frozen=True)
class ListItem:
    product: str
    quantity: float  # in the product's comparable unit (lb, oz, gal, each ...)


@dataclass
class Plan:
    """A concrete assignment of items to stores and what it costs."""

    name: str
    assignments: dict[str, str]  # product -> store
    item_costs: dict[str, float]  # product -> qty * price
    trip_costs: dict[str, float]  # store -> trip cost, for visited stores
    unavailable: list[str] = field(default_factory=list)
    status: str = "Optimal"

    @property
    def items_total(self) -> float:
        return round(sum(self.item_costs.values()), 2)

    @property
    def trips_total(self) -> float:
        return round(sum(self.trip_costs.values()), 2)

    @property
    def total(self) -> float:
        return round(self.items_total + self.trips_total, 2)

    @property
    def stores(self) -> list[str]:
        return sorted(self.trip_costs)

    def by_store(self) -> dict[str, list[tuple[str, float]]]:
        """{store: [(product, cost), ...]} for printing a buy list."""
        out: dict[str, list[tuple[str, float]]] = {s: [] for s in self.stores}
        for product, store in sorted(self.assignments.items()):
            out[store].append((product, self.item_costs[product]))
        return out


@dataclass
class OptimizationResult:
    optimal: Plan
    single_store: Plan | None  # None if no allowed store carries every item
    greedy: Plan
    single_store_candidates: dict[str, float]  # store -> total, for complete stores

    def savings_vs_single_store(self) -> tuple[float, float] | None:
        """($ saved, % saved) of the optimal plan vs the cheapest single store."""
        if self.single_store is None or self.single_store.total == 0:
            return None
        saved = round(self.single_store.total - self.optimal.total, 2)
        return saved, round(100 * saved / self.single_store.total, 1)


def _trip_cost(trip_cost: float | dict[str, float], store: str) -> float:
    return trip_cost.get(store, 0.0) if isinstance(trip_cost, dict) else float(trip_cost)


def merge_duplicates(items: list[ListItem]) -> list[ListItem]:
    """Combine repeated products ('2 lb banana' + '1 lb banana' -> '3 lb banana')."""
    totals: dict[str, float] = {}
    for it in items:
        totals[it.product] = totals.get(it.product, 0.0) + it.quantity
    return [ListItem(p, q) for p, q in totals.items()]


def _available(items: list[ListItem], stores: list[str], prices: dict[PriceKey, float]):
    """Split the list into items some allowed store carries, and the rest."""
    items = merge_duplicates(items)
    carried = [it for it in items if any((it.product, s) in prices for s in stores)]
    missing = [it.product for it in items if it not in carried]
    return carried, missing


def solve_milp(
    items: list[ListItem],
    stores: list[str],
    prices: dict[PriceKey, float],
    trip_cost: float | dict[str, float] = 0.0,
    max_stores: int | None = None,
) -> Plan:
    """Optimal plan via a mixed-integer program solved with CBC."""
    carried, missing = _available(items, stores, prices)
    if not carried:
        return Plan("optimal", {}, {}, {}, missing, status="NoItems")

    prob = pulp.LpProblem("shopping_trip", pulp.LpMinimize)
    pairs = [(i, s) for i, it in enumerate(carried) for s in stores if (it.product, s) in prices]
    x = {(i, s): prob.add_variable(f"x_{i}_{stores.index(s)}", cat="Binary") for (i, s) in pairs}
    y = {s: prob.add_variable(f"y_{k}", cat="Binary") for k, s in enumerate(stores)}

    item_cost = pulp.lpSum(carried[i].quantity * prices[(carried[i].product, s)] * x[i, s]
                           for (i, s) in pairs)
    trips = pulp.lpSum(_trip_cost(trip_cost, s) * y[s] for s in stores)
    prob += item_cost + trips

    for i in range(len(carried)):
        prob += pulp.lpSum(x[i, s] for s in stores if (i, s) in x) == 1, f"buy_{i}"
    for (i, s) in pairs:
        prob += x[i, s] <= y[s], f"visit_{i}_{stores.index(s)}"
    if max_stores is not None:
        prob += pulp.lpSum(y.values()) <= max_stores, "max_stores"

    # CBC ships inside the PuLP wheel, so no separate solver install is needed.
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        return Plan("optimal", {}, {}, {}, missing, status=status)

    assignments: dict[str, str] = {}
    item_costs: dict[str, float] = {}
    for (i, s), var in x.items():
        if var.value() is not None and var.value() > 0.5:
            it = carried[i]
            assignments[it.product] = s
            item_costs[it.product] = round(it.quantity * prices[(it.product, s)], 2)
    used = set(assignments.values())
    trip_costs = {s: _trip_cost(trip_cost, s) for s in used}
    return Plan("optimal", assignments, item_costs, trip_costs, missing, status)


def cheapest_single_store(
    items: list[ListItem],
    stores: list[str],
    prices: dict[PriceKey, float],
    trip_cost: float | dict[str, float] = 0.0,
) -> tuple[Plan | None, dict[str, float]]:
    """Best one-stop plan among stores that carry every (available) item."""
    carried, missing = _available(items, stores, prices)
    totals: dict[str, float] = {}
    plans: dict[str, Plan] = {}
    for s in stores:
        if not carried or not all((it.product, s) in prices for it in carried):
            continue
        costs = {it.product: round(it.quantity * prices[(it.product, s)], 2) for it in carried}
        plan = Plan("single_store", {it.product: s for it in carried}, costs,
                    {s: _trip_cost(trip_cost, s)}, missing)
        plans[s] = plan
        totals[s] = plan.total
    if not plans:
        return None, totals
    best = min(plans, key=lambda s: plans[s].total)
    return plans[best], totals


def greedy_per_item(
    items: list[ListItem],
    stores: list[str],
    prices: dict[PriceKey, float],
    trip_cost: float | dict[str, float] = 0.0,
) -> Plan:
    """Each item at its cheapest store, ignoring trip cost when choosing."""
    carried, missing = _available(items, stores, prices)
    assignments: dict[str, str] = {}
    item_costs: dict[str, float] = {}
    for it in carried:
        best = min((s for s in stores if (it.product, s) in prices),
                   key=lambda s: prices[(it.product, s)])
        assignments[it.product] = best
        item_costs[it.product] = round(it.quantity * prices[(it.product, best)], 2)
    trip_costs = {s: _trip_cost(trip_cost, s) for s in set(assignments.values())}
    return Plan("greedy", assignments, item_costs, trip_costs, missing)


def optimize(
    items: list[ListItem],
    stores: list[str],
    prices: dict[PriceKey, float],
    trip_cost: float | dict[str, float] = 0.0,
    max_stores: int | None = None,
) -> OptimizationResult:
    """Run the MILP and both baselines on the same inputs."""
    optimal = solve_milp(items, stores, prices, trip_cost, max_stores)
    single, candidates = cheapest_single_store(items, stores, prices, trip_cost)
    greedy = greedy_per_item(items, stores, prices, trip_cost)
    return OptimizationResult(optimal, single, greedy, candidates)
