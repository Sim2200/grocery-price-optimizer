"""Watchlist and price-drop alerts."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from grocery_optimizer.alerts import price_alerts
from grocery_optimizer.api import create_app
from grocery_optimizer.catalog import load_catalog
from grocery_optimizer.db import Observation, PriceDB
from grocery_optimizer.extraction import DemoReceiptExtractor


def _obs(price, day, store="Aldi", product="milk (whole)"):
    return Observation(product, store, dt.date(2026, 7, day), price, "gal")


def test_alert_uses_latest_price_per_store():
    obs = [_obs(2.50, 1), _obs(3.40, 20),            # Aldi was cheap, now isn't
           _obs(3.60, 1, "Lidl"), _obs(2.90, 15, "Lidl")]  # Lidl just dropped
    [alert] = price_alerts({"milk (whole)": 3.00}, obs)
    assert (alert.store, alert.price, alert.previous_price) == ("Lidl", 2.90, 3.60)
    assert alert.observed_date == dt.date(2026, 7, 15)


def test_alert_at_exact_target_and_single_observation():
    [alert] = price_alerts({"milk (whole)": 3.00}, [_obs(3.00, 1)])
    assert alert.previous_price is None


def test_no_alert_above_target_or_for_unwatched_products():
    obs = [_obs(3.50, 1), _obs(0.10, 1, product="banana")]
    assert price_alerts({"milk (whole)": 3.00}, obs) == []


def test_alerts_sorted_cheapest_first():
    obs = [_obs(2.9, 1, "Aldi"), _obs(2.5, 1, "Giant")]
    assert [a.store for a in price_alerts({"milk (whole)": 3.0}, obs)] == ["Giant", "Aldi"]


def test_db_watchlist_roundtrip():
    db = PriceDB(":memory:")
    db.sync_catalog(load_catalog())
    db.set_watch("milk (whole)", 3.0)
    db.set_watch("milk (whole)", 2.5)  # updates, doesn't duplicate
    db.set_watch("banana", 0.5)
    assert db.watchlist() == {"banana": 0.5, "milk (whole)": 2.5}
    db.delete_watch("banana")
    assert db.watchlist() == {"milk (whole)": 2.5}
    with pytest.raises(KeyError):
        db.set_watch("unicorn", 1.0)
    db.reset_data()
    assert db.watchlist() == {"milk (whole)": 2.5}  # the watchlist survives a data reset
    db.close()


@pytest.fixture
def demo_client(tmp_path):
    app = create_app(db_path=tmp_path / "t.db", extractor=DemoReceiptExtractor())
    with TestClient(app) as c:
        c.post("/api/demo/load", json={"reset": True})
        yield c


def test_watchlist_api(demo_client):
    c = demo_client
    assert c.get("/api/watchlist").json() == []
    # A very high target triggers at every store that sells milk; a tiny one at none.
    rows = c.put("/api/watchlist", json={"product": "milk (whole)", "target_price": 100}).json()
    [milk] = rows
    assert milk["unit"] == "gal" and milk["best_store"] and milk["best_price"] is not None
    assert len(milk["alerts"]) >= 2
    assert milk["alerts"][0]["price"] == milk["best_price"]
    assert len(c.get("/api/alerts").json()) == len(milk["alerts"])

    c.put("/api/watchlist", json={"product": "milk (whole)", "target_price": 0.01})
    assert c.get("/api/alerts").json() == []

    assert c.put("/api/watchlist", json={"product": "unicorn", "target_price": 1}).status_code == 422
    assert c.put("/api/watchlist", json={"product": "banana", "target_price": 0}).status_code == 422
    assert c.delete("/api/watchlist/milk (whole)").status_code == 204
    assert c.get("/api/watchlist").json() == []
    assert c.delete("/api/watchlist/unicorn").status_code == 404
