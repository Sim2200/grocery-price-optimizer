"""Optimizer tests. The small cases are designed to be checked by hand."""

import itertools
import random

import pytest

from grocery_optimizer.optimizer import (
    ListItem,
    cheapest_single_store,
    greedy_per_item,
    optimize,
    solve_milp,
)

# Two stores, three items. Item costs (qty x unit price):
#            A      B
#   milk    3.00   4.00
#   bread   4.00   2.00
#   eggs    3.00   3.60   (12 x 0.25 vs 12 x 0.30)
#   total  10.00   9.60
PRICES = {
    ("milk", "A"): 3.00, ("milk", "B"): 4.00,
    ("bread", "A"): 4.00, ("bread", "B"): 2.00,
    ("eggs", "A"): 0.25, ("eggs", "B"): 0.30,
}
ITEMS = [ListItem("milk", 1), ListItem("bread", 1), ListItem("eggs", 12)]
STORES = ["A", "B"]


def test_multi_store_beats_single_store_when_trips_are_cheap():
    # Trip cost $1. Best single store: B = 9.60 + 1 = 10.60.
    # Split: milk@A 3 + bread@B 2 + eggs@A 3 = 8.00 + 2 trips = 10.00.
    result = optimize(ITEMS, STORES, PRICES, trip_cost=1.0)
    assert result.single_store.stores == ["B"]
    assert result.single_store.total == pytest.approx(10.60)
    assert result.optimal.total == pytest.approx(10.00)
    assert result.optimal.assignments == {"milk": "A", "bread": "B", "eggs": "A"}
    saved, pct = result.savings_vs_single_store()
    assert saved == pytest.approx(0.60)
    assert pct == pytest.approx(5.7)


def test_trip_cost_makes_single_store_win():
    # Trip cost $5. Split would be 8.00 + 10 = 18.00; one trip to B is 9.60 + 5 = 14.60.
    result = optimize(ITEMS, STORES, PRICES, trip_cost=5.0)
    assert result.optimal.stores == ["B"]
    assert result.optimal.total == pytest.approx(14.60)
    assert result.savings_vs_single_store() == (0.0, 0.0)
    # Greedy ignores trip cost and ends up worse than the optimum.
    assert result.greedy.total == pytest.approx(18.00)


def test_greedy_matches_optimum_when_trips_are_free():
    result = optimize(ITEMS, STORES, PRICES, trip_cost=0.0)
    assert result.greedy.total == pytest.approx(result.optimal.total) == pytest.approx(8.00)


def test_max_stores_one_equals_single_store_baseline():
    plan = solve_milp(ITEMS, STORES, PRICES, trip_cost=1.0, max_stores=1)
    single, _ = cheapest_single_store(ITEMS, STORES, PRICES, trip_cost=1.0)
    assert plan.total == pytest.approx(single.total)
    assert len(plan.stores) == 1


def test_per_store_trip_costs():
    # A is right next door (free), B is far ($3): buy everything at A.
    result = optimize(ITEMS, STORES, PRICES, trip_cost={"A": 0.0, "B": 3.0})
    # All at A = 10.00; split = 8.00 + 3 = 11.00.
    assert result.optimal.total == pytest.approx(10.00)
    assert result.optimal.stores == ["A"]


def test_items_missing_at_some_stores():
    prices = {**PRICES, ("tofu", "A"): 2.50}  # only A sells tofu
    items = ITEMS + [ListItem("tofu", 1), ListItem("saffron", 1)]  # nobody sells saffron
    result = optimize(items, STORES, prices, trip_cost=1.0)
    assert result.optimal.unavailable == ["saffron"]
    assert result.optimal.assignments["tofu"] == "A"
    # Only A carries every available item, so it is the single-store baseline.
    assert result.single_store.stores == ["A"]
    assert set(result.single_store_candidates) == {"A"}


def test_no_single_store_carries_everything():
    prices = {("x", "A"): 1.0, ("y", "B"): 1.0}
    result = optimize([ListItem("x", 1), ListItem("y", 1)], ["A", "B"], prices, trip_cost=1.0)
    assert result.single_store is None
    assert result.savings_vs_single_store() is None
    assert result.optimal.total == pytest.approx(4.0)


def test_only_allowed_stores_are_used():
    result = optimize(ITEMS, ["A"], PRICES, trip_cost=1.0)
    assert set(result.optimal.assignments.values()) == {"A"}


def test_duplicate_list_items_are_merged():
    items = [ListItem("eggs", 6), ListItem("eggs", 6)]
    plan = greedy_per_item(items, STORES, PRICES)
    assert plan.item_costs["eggs"] == pytest.approx(3.00)


def _brute_force(items, stores, prices, trip, max_stores=None):
    best = float("inf")
    for k in range(1, len(stores) + 1):
        if max_stores is not None and k > max_stores:
            break
        for subset in itertools.combinations(stores, k):
            total, used = 0.0, set()
            feasible = True
            for it in items:
                options = [(it.quantity * prices[(it.product, s)], s)
                           for s in subset if (it.product, s) in prices]
                if not options:
                    feasible = False
                    break
                cost, store = min(options)
                total += cost
                used.add(store)
            if feasible:
                best = min(best, total + trip * len(used))
    return best


@pytest.mark.parametrize("seed", range(15))
def test_milp_matches_brute_force_on_random_instances(seed):
    rng = random.Random(seed)
    stores = [f"S{k}" for k in range(4)]
    products = [f"p{k}" for k in range(8)]
    prices = {}
    for p in products:
        for s in stores:
            if rng.random() < 0.8:
                prices[(p, s)] = round(rng.uniform(1, 10), 2)
        if not any((p, s) in prices for s in stores):
            prices[(p, stores[0])] = 5.0
    items = [ListItem(p, rng.choice([1, 2, 3])) for p in products]
    trip = rng.choice([0.0, 2.0, 5.0, 10.0])
    max_stores = rng.choice([None, 2])
    plan = solve_milp(items, stores, prices, trip, max_stores)
    expected = _brute_force(items, stores, prices, trip, max_stores)
    if expected == float("inf"):
        assert plan.status != "Optimal"
    else:
        assert plan.total == pytest.approx(expected, abs=0.02)
