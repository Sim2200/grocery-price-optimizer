"""Manual entry: CSV rows -> `Receipt` objects.

One row per line item. Rows with the same (store, date) form one receipt.

    store,date,raw_name,quantity,unit,size,unit_price,line_total,total
    Aldi,2026-07-02,ORG BANANAS,2.1,lb,,0.79,1.66,
    Aldi,2026-07-02,WHOLE MILK,1,each,1 gal,3.29,3.29,4.95

`size` and `total` may be blank; `total` is taken from the first non-blank
row of each receipt. The web UI sends CSV text to the same parser.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections import OrderedDict

from pydantic import ValidationError

from .schemas import LineItem, Receipt

CSV_COLUMNS = ["store", "date", "raw_name", "quantity", "unit", "size", "unit_price", "line_total", "total"]
REQUIRED_COLUMNS = {"store", "raw_name", "quantity", "unit", "unit_price", "line_total"}

CSV_TEMPLATE = ",".join(CSV_COLUMNS) + "\n" + "Aldi,2026-07-02,ORG BANANAS,2.1,lb,,0.79,1.66,\n"


class ManualEntryError(ValueError):
    pass


def _blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def receipts_from_rows(rows: list[dict]) -> list[Receipt]:
    """Group dict rows (from a CSV or a form) into validated receipts."""
    groups: OrderedDict[tuple[str, str], list[tuple[int, dict]]] = OrderedDict()
    for line_no, row in enumerate(rows, start=2):  # line 1 is the CSV header
        if all(_blank(v) for v in row.values()):
            continue
        missing = [c for c in REQUIRED_COLUMNS if _blank(row.get(c))]
        if missing:
            raise ManualEntryError(f"Row {line_no}: missing {', '.join(sorted(missing))}")
        key = (str(row["store"]).strip(), str(row.get("date") or "").strip())
        groups.setdefault(key, []).append((line_no, row))

    receipts: list[Receipt] = []
    for (store, date_text), group in groups.items():
        items: list[LineItem] = []
        total: float | None = None
        for line_no, row in group:
            try:
                items.append(LineItem(
                    raw_name=str(row["raw_name"]),
                    quantity=float(row["quantity"]),
                    unit=str(row["unit"]).strip().lower(),
                    size=None if _blank(row.get("size")) else str(row["size"]).strip(),
                    unit_price=float(row["unit_price"]),
                    line_total=float(row["line_total"]),
                ))
            except (ValidationError, ValueError) as exc:
                raise ManualEntryError(f"Row {line_no}: {exc}") from exc
            if total is None and not _blank(row.get("total")):
                total = float(row["total"])
        try:
            date = dt.date.fromisoformat(date_text) if date_text else None
        except ValueError as exc:
            raise ManualEntryError(f"Bad date '{date_text}' for {store}; use YYYY-MM-DD") from exc
        receipts.append(Receipt(store=store, date=date, line_items=items, total=total))
    return receipts


def receipts_from_csv(text: str) -> list[Receipt]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ManualEntryError("CSV is empty")
    header = {name.strip() for name in reader.fieldnames}
    missing = REQUIRED_COLUMNS - header
    if missing:
        raise ManualEntryError(f"CSV is missing columns: {', '.join(sorted(missing))}")
    rows = [{(k or "").strip(): v for k, v in row.items()} for row in reader]
    return receipts_from_rows(rows)
