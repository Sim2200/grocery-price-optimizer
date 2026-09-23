"""Optimizer benchmark on the bundled SYNTHETIC price database.

1. The sample shopping list (data/sample_shopping_list.csv) at several trip costs.
2. 500 random shopping lists (8-15 products, fixed seed) at trip costs $0, $2, $5.

Compares the MILP plan with the cheapest single store and the per-item greedy
baseline. All prices are synthetic, so these numbers describe the method on
made-up data, not real-world savings.

Run: python evals/optimizer_benchmark.py
"""

from __future__ import annotations

import random
import statistics
import time
from pathlib import Path

from grocery_optimizer.ingest import load_demo_data, open_db
from grocery_optimizer.optimizer import ListItem, optimize
from grocery_optimizer.planning import read_shopping_list
from grocery_optimizer.pricing import current_prices, price_table

ROOT = Path(__file__).resolve().parent.parent
N_LISTS = 500
SEED = 42


def main() -> None:
    db = open_db(":memory:")
    load_demo_data(db)
    prices = price_table(current_prices(db.observations()))
    stores = db.store_names()
    units = {p.name: p.unit for p in db.products()}
    products = sorted({p for p, _ in prices})

    print("SYNTHETIC data. Sample shopping list:")
    print(f"{'trip $':>7}{'MILP':>10}{'single':>10}{'greedy':>10}{'saved vs single':>18}  stores used")
    items = read_shopping_list((ROOT / "data" / "sample_shopping_list.csv").read_text())
    for trip in (0, 1, 2, 3, 5, 10):
        r = optimize(items, stores, prices, trip_cost=trip)
        s = r.savings_vs_single_store()
        single = f"{r.single_store.total:>10.2f}" if r.single_store else f"{'n/a':>10}"
        saved = f"${s[0]:.2f} ({s[1]:.1f}%)" if s else "n/a"
        print(f"{trip:>7}{r.optimal.total:>10.2f}{single}{r.greedy.total:>10.2f}{saved:>18}  "
              f"{', '.join(r.optimal.stores)}")

    rng = random.Random(SEED)
    lists = []
    for _ in range(N_LISTS):
        chosen = rng.sample(products, k=rng.randint(8, 15))
        lists.append([ListItem(p, {"lb": 2, "each": 4, "gal": 1}.get(units[p], 16)) for p in chosen])

    print(f"\n{N_LISTS} random lists of 8-15 products (seed {SEED}):")
    print(f"{'trip $':>7}{'has single':>12}{'mean % vs single':>18}{'max %':>8}"
          f"{'mean % vs greedy':>18}{'avg stores':>12}{'avg solve ms':>14}")
    for trip in (0, 2, 5):
        vs_single, vs_greedy, n_stores, times, has_single = [], [], [], [], 0
        for lst in lists:
            t0 = time.perf_counter()
            r = optimize(lst, stores, prices, trip_cost=trip)
            times.append((time.perf_counter() - t0) * 1000)
            n_stores.append(len(r.optimal.stores))
            vs_greedy.append(100 * (r.greedy.total - r.optimal.total) / r.greedy.total)
            s = r.savings_vs_single_store()
            if s is not None:
                has_single += 1
                vs_single.append(s[1])
        print(f"{trip:>7}{has_single / N_LISTS:>12.0%}{statistics.mean(vs_single):>18.1f}"
              f"{max(vs_single):>8.1f}{statistics.mean(vs_greedy):>18.1f}"
              f"{statistics.mean(n_stores):>12.2f}{statistics.mean(times):>14.1f}")
    print("\n'avg solve ms' times one optimize() call: the MILP plus both baselines.")


if __name__ == "__main__":
    main()
