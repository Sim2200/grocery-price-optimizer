"""Spending insights: breakdowns and the "what if I had used the planner" replay."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from grocery_optimizer.api import create_app
from grocery_optimizer.catalog import load_catalog
from grocery_optimizer.db import PriceDB
from grocery_optimizer.extraction import DemoReceiptExtractor
from grocery_optimizer.insights import replay_trips, spend_breakdown
from grocery_optimizer.matching import MatchResult
from grocery_optimizer.schemas import LineItem, Receipt


def _save(db, store, day, lines):
    receipt = Receipt(store=store, date=dt.date(2026, 7, day), line_items=[
        LineItem(raw_name=name, quantity=qty, unit=unit, size=size, unit_price=price,
                 line_total=round(qty * price, 2))
        for name, qty, unit, size, price, _ in lines])
    matches = [MatchResult(name, product, 100.0, "fuzzy", False)
               for name, *_, product in lines]
    return db.insert_receipt(receipt, matches, source="manual")


@pytest.fixture
def db():
    database = PriceDB(":memory:")
    database.sync_catalog(load_catalog())
    # July 1 at Lidl: milk $3.00/gal, bananas $0.60/lb.
    _save(database, "Lidl", 1, [("MILK", 1, "each", "1 gal", 3.00, "milk (whole)"),
                                ("BANANAS", 1, "lb", None, 0.60, "banana")])
    # July 10 at Aldi: milk $4.00, 2 lb bananas at $0.50, and one unmatched line.
    _save(database, "Aldi", 10, [("MILK", 1, "each", "1 gal", 4.00, "milk (whole)"),
                                 ("BANANAS", 2, "lb", None, 0.50, "banana"),
                                 ("GIFT CARD", 1, "each", None, 25.00, None)])
    # July 20 at Lidl: a milk sale that the July 10 trip could not have known about.
    _save(database, "Lidl", 20, [("MILK", 1, "each", "1 gal", 1.00, "milk (whole)")])
    yield database
    database.close()


def test_replay_is_hand_checkable(db):
    trips = {t.receipt_id: t for t in replay_trips(db.line_items(), db.observations(), 0.5)}
    aldi = trips[2]
    # Paid at Aldi: 4.00 + 1.00 + one $0.50 trip = 5.50.
    # Known on July 10: all at Lidl = 3.00 + 2 x 0.60 + 0.50 = 4.70
    # (the July 20 sale is ignored, and the gift card has no comparable price).
    assert aldi.actual == pytest.approx(5.50)
    assert aldi.optimal == pytest.approx(4.70)
    assert aldi.saved == pytest.approx(0.80)
    assert aldi.stores_in_plan == ["Lidl"]


def test_trip_cost_changes_the_answer(db):
    aldi = {t.receipt_id: t for t in replay_trips(db.line_items(), db.observations(), 0.0)}[2]
    # Free trips: milk at Lidl (3.00) and bananas at Aldi (1.00) is cheapest.
    assert aldi.optimal == pytest.approx(4.00)
    assert sorted(aldi.stores_in_plan) == ["Aldi", "Lidl"]


def test_first_trip_cannot_save_and_savings_never_negative(db):
    trips = replay_trips(db.line_items(), db.observations(), 5.0)
    assert trips[0].saved == 0  # nothing else was known on July 1
    assert all(t.saved >= 0 for t in trips)


def test_spend_breakdown(db):
    categories = {p.name: p.category for p in db.products()}
    breakdown = spend_breakdown(db.line_items(), categories)
    assert dict(breakdown["by_store"]) == {"Aldi": 30.00, "Lidl": 4.60}
    assert dict(breakdown["by_category"]) == {"unmatched": 25.00, "produce": 1.60, "dairy": 8.00}
    assert breakdown["by_month"] == [("2026-07", 34.60)]
    assert breakdown["by_store"][0][0] == "Aldi"  # largest first


def test_insights_api_on_demo_data(tmp_path):
    app = create_app(db_path=tmp_path / "t.db", extractor=DemoReceiptExtractor())
    with TestClient(app) as c:
        empty = c.get("/api/insights").json()
        assert empty["total_spend"] == 0 and empty["trips"] == []
        c.post("/api/demo/load", json={"reset": True})
        body = c.get("/api/insights", params={"trip_cost": 2}).json()
        assert body["receipts"] == 16 and len(body["trips"]) == 16
        assert sum(a["amount"] for a in body["by_store"]) == pytest.approx(body["total_spend"], abs=0.05)
        assert body["actual_total"] - body["optimal_total"] == pytest.approx(body["estimated_savings"], abs=0.01)
        assert all(t["saved"] >= 0 for t in body["trips"])
        assert [m["label"] for m in body["by_month"]] == sorted(m["label"] for m in body["by_month"])
        assert c.get("/api/insights", params={"trip_cost": -1}).status_code == 422
