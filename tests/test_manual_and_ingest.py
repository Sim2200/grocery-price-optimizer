import json

import pytest

from grocery_optimizer.config import SYNTHETIC_RECEIPTS_DIR
from grocery_optimizer.ingest import (
    add_custom_product,
    build_matcher,
    canonical_store_name,
    ingest_receipt,
    load_demo_data,
    match_receipt,
    open_db,
    save_receipt,
)
from grocery_optimizer.manual_entry import CSV_TEMPLATE, ManualEntryError, receipts_from_csv
from grocery_optimizer.matching import MatchResult
from grocery_optimizer.planning import plan_trip, read_shopping_list

CSV = """store,date,raw_name,quantity,unit,size,unit_price,line_total,total
Aldi,2026-07-02,ORG BANANAS,2.1,lb,,0.79,1.66,4.95
Aldi,2026-07-02,WHOLE MILK,1,each,1 gal,3.29,3.29,
Giant,2026-07-03,LG EGGS,1,each,12 ct,3.60,3.60,3.60
"""


def test_csv_groups_rows_into_receipts():
    receipts = receipts_from_csv(CSV)
    assert [r.store for r in receipts] == ["Aldi", "Giant"]
    assert len(receipts[0].line_items) == 2
    assert receipts[0].total == 4.95
    assert receipts[0].line_items[1].size == "1 gal"
    assert receipts[0].line_items[0].size is None


def test_csv_template_parses():
    assert receipts_from_csv(CSV_TEMPLATE)[0].store == "Aldi"


def test_csv_errors_point_at_the_row():
    with pytest.raises(ManualEntryError, match="missing columns"):
        receipts_from_csv("store,raw_name\nAldi,x\n")
    with pytest.raises(ManualEntryError, match="Row 2"):
        receipts_from_csv(CSV.replace("2.1,lb", "abc,lb"))
    with pytest.raises(ManualEntryError, match="Row 2"):
        receipts_from_csv(CSV.replace(",lb,", ",furlong,"))
    with pytest.raises(ManualEntryError, match="Bad date"):
        receipts_from_csv(CSV.replace("2026-07-02", "July 2"))


@pytest.mark.parametrize("raw, known, expected", [
    ("TRADER JOE'S #552", [], "Trader Joe's"),
    ("ALDI", [], "Aldi"),
    ("Aldi Store 1234", ["Aldi"], "Aldi"),
    ("Trader Joes", ["Trader Joe's"], "Trader Joe's"),
])
def test_canonical_store_name(raw, known, expected):
    assert canonical_store_name(raw, known) == expected


def test_ingest_csv_end_to_end():
    db = open_db(":memory:")
    for receipt in receipts_from_csv(CSV):
        ingest_receipt(db, receipt, source="manual")
    assert db.store_names() == ["Aldi", "Giant"]
    prices = {(o.product, o.store): round(o.unit_price, 4) for o in db.observations()}
    assert prices == {
        ("banana (organic)", "Aldi"): 0.79,
        ("milk (whole)", "Aldi"): 3.29,
        ("eggs (large)", "Giant"): 0.30,
    }


def test_user_corrections_become_aliases():
    db = open_db(":memory:")
    receipt = receipts_from_csv(CSV)[0]
    matches = match_receipt(receipt, build_matcher(db))
    # User says "WHOLE MILK" was actually 2% milk.
    matches[1] = MatchResult("WHOLE MILK", "milk (2%)", 100, "user", False)
    save_receipt(db, receipt, matches, source="manual")
    assert db.aliases()["whole milk"] == "milk (2%)"
    assert build_matcher(db).match("Whole Milk").product == "milk (2%)"


def test_custom_product_is_matchable():
    db = open_db(":memory:")
    add_custom_product(db, "kimchi", "oz", "deli")
    assert build_matcher(db).match("KIMCHI 16 OZ").product == "kimchi"


def test_demo_data_loads_and_plans():
    db = open_db(":memory:")
    n = load_demo_data(db)
    assert n == len(list(SYNTHETIC_RECEIPTS_DIR.glob("SYNTHETIC_*.json"))) > 0
    assert db.line_items(only_unmatched=True) == []
    items = read_shopping_list("product,quantity\nmilk (whole),1\neggs (large),12\nbanana,2\n")
    result = plan_trip(db, items, trip_cost=3.0)
    assert result.optimal.status == "Optimal"
    assert result.optimal.total <= result.greedy.total + 1e-9
    if result.single_store is not None:
        assert result.optimal.total <= result.single_store.total + 1e-9


def test_synthetic_files_are_labeled():
    files = list(SYNTHETIC_RECEIPTS_DIR.glob("*.json"))
    assert files and all(f.name.startswith("SYNTHETIC_") for f in files)
    json.loads(files[0].read_text())
