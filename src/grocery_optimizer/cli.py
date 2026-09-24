"""Command-line interface.

    python -m grocery_optimizer.cli demo --reset          load the SYNTHETIC sample receipts
    python -m grocery_optimizer.cli ingest receipt.jpg    extract (LLM) + match + save
    python -m grocery_optimizer.cli ingest my.csv         manual CSV entry
    python -m grocery_optimizer.cli prices                current price per product and store
    python -m grocery_optimizer.cli plan list.csv --trip-cost 5 [--stores Aldi Lidl] [--max-stores 2]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import DATABASE_URL
from .extraction import ExtractionError, get_extractor
from .ingest import ingest_receipt, load_demo_data, open_db
from .manual_entry import receipts_from_csv
from .optimizer import Plan
from .planning import plan_trip, read_shopping_list
from .pricing import current_prices


def _print_plan(plan: Plan, title: str) -> None:
    print(f"\n{title}: ${plan.total:.2f}  (items ${plan.items_total:.2f} + trips ${plan.trips_total:.2f})")
    for store, lines in plan.by_store().items():
        print(f"  {store} (trip ${plan.trip_costs[store]:.2f})")
        for product, cost in lines:
            print(f"    {product:<30} ${cost:>7.2f}")


def cmd_demo(args: argparse.Namespace) -> None:
    db = open_db(args.db)
    if args.reset:
        db.reset_data()
    n = load_demo_data(db)
    print(f"Loaded {n} SYNTHETIC receipts into {args.db}")


def cmd_ingest(args: argparse.Namespace) -> None:
    db = open_db(args.db)
    for path in map(Path, args.files):
        if path.suffix.lower() == ".csv":
            receipts, source = receipts_from_csv(path.read_text()), "manual"
        else:
            try:
                receipts, source = [get_extractor().extract(path.read_bytes(), path.name)], "llm"
            except ExtractionError as exc:
                print(f"{path.name}: {exc}")
                continue
        for receipt in receipts:
            _, matches = ingest_receipt(db, receipt, source=source, file_name=path.name)
            review = [mr.raw_name for mr in matches if mr.needs_review]
            print(f"{path.name}: {receipt.store}, {len(matches)} lines, {len(review)} need review")
            for name in review:
                print(f"   review: {name}")


def cmd_prices(args: argparse.Namespace) -> None:
    db = open_db(args.db)
    estimates = current_prices(db.observations(), method=args.method)
    stores = db.store_names()
    print(f"{'product':<28}" + "".join(f"{s[:12]:>14}" for s in stores))
    units = {p.name: p.unit for p in db.products()}
    for product in sorted({p for p, _ in estimates}):
        cells = [estimates.get((product, s)) for s in stores]
        print(f"{product[:27]:<28}" + "".join(
            f"{('$%.3f/%s' % (c.price, units[product])) if c else '-':>14}" for c in cells))


def cmd_plan(args: argparse.Namespace) -> None:
    db = open_db(args.db)
    items = read_shopping_list(Path(args.shopping_list).read_text())
    result = plan_trip(db, items, args.stores, args.trip_cost, args.max_stores, args.method)
    _print_plan(result.optimal, "Optimal plan (MILP)")
    if result.single_store:
        _print_plan(result.single_store, "Cheapest single store")
    else:
        print("\nNo single store carries every item.")
    _print_plan(result.greedy, "Per-item greedy (ignores trip cost)")
    savings = result.savings_vs_single_store()
    if savings:
        print(f"\nSavings vs cheapest single store: ${savings[0]:.2f} ({savings[1]:.1f}%)")
    if result.optimal.unavailable:
        print("Not available at the chosen stores:", ", ".join(result.optimal.unavailable))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="grocery", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=DATABASE_URL,
                        help="SQLite file path or SQLAlchemy URL (default: $DATABASE_URL or $GROCERY_DB)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("demo", help="load bundled SYNTHETIC receipts")
    p.add_argument("--reset", action="store_true", help="wipe existing receipts first")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("ingest", help="ingest receipt images/PDFs (LLM) or CSV files")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("prices", help="show current prices")
    p.add_argument("--method", choices=["weighted", "latest"], default="weighted")
    p.set_defaults(func=cmd_prices)

    p = sub.add_parser("plan", help="plan a shopping trip")
    p.add_argument("shopping_list", help="CSV with product,quantity")
    p.add_argument("--trip-cost", type=float, default=5.0)
    p.add_argument("--stores", nargs="*", default=None)
    p.add_argument("--max-stores", type=int, default=None)
    p.add_argument("--method", choices=["weighted", "latest"], default="weighted")
    p.set_defaults(func=cmd_plan)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
