import datetime as dt

import pytest

from grocery_optimizer.catalog import load_catalog
from grocery_optimizer.db import Observation, PriceDB
from grocery_optimizer.matching import MatchResult
from grocery_optimizer.pricing import current_prices, price_table, recency_weight
from grocery_optimizer.schemas import LineItem, Receipt


def _match(product, method="fuzzy"):
    return MatchResult("", product, 100.0 if product else 40.0, method, product is None)


@pytest.fixture
def db():
    database = PriceDB(":memory:")
    database.sync_catalog(load_catalog())
    yield database
    database.close()


def _receipt(store="Aldi", date=dt.date(2026, 7, 1)):
    return Receipt(
        store=store,
        date=date,
        total=9.48,
        line_items=[
            LineItem(raw_name="ORG BANANAS", quantity=2.0, unit="lb", unit_price=0.79, line_total=1.58),
            LineItem(raw_name="WHOLE MILK", quantity=1, unit="each", size="1 gal", unit_price=3.40, line_total=3.40),
            LineItem(raw_name="LOOSE THING", quantity=1, unit="each", unit_price=4.50, line_total=4.50),
        ],
    )


def test_insert_receipt_creates_observations(db):
    matches = [_match("banana (organic)"), _match("milk (whole)"), _match(None, "unmatched")]
    receipt_id = db.insert_receipt(_receipt(), matches, source="manual")
    obs = db.observations()
    assert {(o.product, o.store, o.unit_price) for o in obs} == {
        ("banana (organic)", "Aldi", 0.79),
        ("milk (whole)", "Aldi", 3.40),
    }
    summary = db.receipts()[0]
    assert summary["id"] == receipt_id and summary["n_items"] == 3 and summary["n_unmatched"] == 1
    assert len(db.line_items(only_unmatched=True)) == 1


def test_mismatched_match_count_is_rejected(db):
    with pytest.raises(ValueError):
        db.insert_receipt(_receipt(), [_match("banana")], source="manual")


def test_rematch_updates_observation_and_saves_alias(db):
    matches = [_match("banana (organic)"), _match("milk (whole)"), _match(None, "unmatched")]
    db.insert_receipt(_receipt(), matches, source="manual")
    loose = db.line_items(only_unmatched=True)[0]
    # "LOOSE THING" is really a 1-each avocado.
    db.rematch_line_item(loose["id"], "avocado (hass)")
    prices = {(o.product, o.store): o.unit_price for o in db.observations()}
    assert prices[("avocado (hass)", "Aldi")] == pytest.approx(4.50)
    assert db.aliases()["loose thing"] == "avocado (hass)"
    assert db.alias_rows()[0]["source"] == "user"


def test_user_alias_is_not_overwritten_by_automation(db):
    db.set_alias("MYSTERY", "rolled oats", source="user")
    db.set_alias("MYSTERY", "banana", source="fuzzy")
    assert db.aliases()["mystery"] == "rolled oats"
    db.set_alias("MYSTERY", "banana", source="user")
    assert db.aliases()["mystery"] == "banana"


def test_unit_mismatch_produces_no_observation(db):
    # Banana priced per lb in the catalog, but receipt line is per-each with no size.
    receipt = Receipt(store="Lidl", line_items=[
        LineItem(raw_name="BANANA", quantity=3, unit="each", unit_price=0.25, line_total=0.75)])
    db.insert_receipt(receipt, [_match("banana")], source="manual")
    assert db.observations() == []
    assert db.line_items()[0]["product"] == "banana"


def test_delete_receipt_cascades(db):
    db.insert_receipt(_receipt(), [_match("banana (organic)"), _match("milk (whole)"), _match(None)],
                      source="manual")
    db.delete_receipt(db.receipts()[0]["id"])
    assert db.receipts() == [] and db.observations() == [] and db.line_items() == []


def test_file_backed_db_persists(tmp_path):
    path = tmp_path / "prices.db"
    first = PriceDB(path)
    first.sync_catalog(load_catalog())
    first.insert_receipt(_receipt(), [_match("banana (organic)"), _match("milk (whole)"), _match(None)],
                         source="manual")
    first.close()
    second = PriceDB(path)
    assert len(second.observations()) == 2


def _obs(price, day, product="milk (whole)", store="Aldi"):
    return Observation(product, store, dt.date(2026, 7, day), price, "gal")


def test_latest_price():
    est = current_prices([_obs(3.00, 1), _obs(4.00, 20), _obs(3.50, 10)], method="latest")
    assert est[("milk (whole)", "Aldi")].price == pytest.approx(4.00)
    assert est[("milk (whole)", "Aldi")].n_observations == 3


def test_recency_weighted_price_is_hand_checkable():
    # Observations 30 days apart with a 30-day half-life: weights 1.0 and 0.5.
    # (1.0 * 4.00 + 0.5 * 3.00) / 1.5 = 3.6667
    obs = [
        Observation("milk (whole)", "Aldi", dt.date(2026, 6, 1), 3.00, "gal"),
        Observation("milk (whole)", "Aldi", dt.date(2026, 7, 1), 4.00, "gal"),
    ]
    est = current_prices(obs, method="weighted", half_life_days=30)
    assert est[("milk (whole)", "Aldi")].price == pytest.approx(3.6667, abs=1e-4)
    assert recency_weight(30, 30) == pytest.approx(0.5)


def test_prices_are_per_product_and_store():
    obs = [_obs(3.0, 1), _obs(5.0, 1, store="Giant"), _obs(1.0, 1, product="banana")]
    table = price_table(current_prices(obs))
    assert table == {("milk (whole)", "Aldi"): 3.0, ("milk (whole)", "Giant"): 5.0, ("banana", "Aldi"): 1.0}


def test_bad_method():
    with pytest.raises(ValueError):
        current_prices([], method="median")
