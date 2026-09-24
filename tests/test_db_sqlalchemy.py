"""SQLAlchemy-specific behaviour of the price database."""

import datetime as dt
import sqlite3

from sqlalchemy import text

from grocery_optimizer.catalog import load_catalog
from grocery_optimizer.db import PriceDB, database_url
from grocery_optimizer.matching import MatchResult
from grocery_optimizer.schemas import LineItem, Receipt


def _receipt():
    return Receipt(store="Aldi", date=dt.date(2026, 7, 1), total=1.58, line_items=[
        LineItem(raw_name="ORG BANANAS", quantity=2.0, unit="lb", unit_price=0.79, line_total=1.58)])


def _match(product):
    return MatchResult("", product, 100.0, "fuzzy", False)


def test_database_url_accepts_paths_memory_and_urls(tmp_path):
    assert database_url(":memory:") == "sqlite://"
    assert database_url(tmp_path / "a.db") == f"sqlite:///{tmp_path / 'a.db'}"
    pg = "postgresql+psycopg://user:pw@localhost:5432/grocery"
    assert database_url(pg) == pg


def test_sqlalchemy_url_works_like_a_path(tmp_path):
    url = f"sqlite:///{tmp_path / 'via-url.db'}"
    db = PriceDB(url)
    db.sync_catalog(load_catalog())
    db.insert_receipt(_receipt(), [_match("banana (organic)")], source="manual")
    db.close()
    assert len(PriceDB(tmp_path / "via-url.db").observations()) == 1


def test_sqlite_foreign_keys_are_enforced():
    db = PriceDB(":memory:")
    assert db.session.execute(text("PRAGMA foreign_keys")).scalar() == 1
    db.close()


def test_each_memory_db_is_independent():
    first, second = PriceDB(":memory:"), PriceDB(":memory:")
    first.upsert_store("Aldi")
    assert first.store_names() == ["Aldi"] and second.store_names() == []
    first.close()
    second.close()


def test_rematch_replaces_observation_and_ignores_missing_line():
    db = PriceDB(":memory:")
    db.sync_catalog(load_catalog())
    db.insert_receipt(_receipt(), [_match("banana (organic)")], source="manual")
    line_id = db.line_items()[0]["id"]
    db.rematch_line_item(line_id, "banana", remember=False)
    assert [(o.product, o.unit_price) for o in db.observations()] == [("banana", 0.79)]
    db.rematch_line_item(line_id, None)
    assert db.observations() == []
    db.rematch_line_item(9999, "banana")  # unknown id: no error, nothing changes
    db.close()


# The raw-sqlite3 schema this project used before moving to SQLAlchemy.
OLD_SCHEMA = """
CREATE TABLE stores (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, unit TEXT NOT NULL,
                       category TEXT NOT NULL DEFAULT 'other');
CREATE TABLE aliases (alias TEXT PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id)
                      ON DELETE CASCADE, source TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE receipts (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
                       purchase_date TEXT, total REAL, source TEXT NOT NULL, file_name TEXT,
                       created_at TEXT NOT NULL);
CREATE TABLE line_items (id INTEGER PRIMARY KEY, receipt_id INTEGER NOT NULL REFERENCES
                         receipts(id) ON DELETE CASCADE, raw_name TEXT NOT NULL,
                         quantity REAL NOT NULL, unit TEXT NOT NULL, size TEXT,
                         unit_price REAL NOT NULL, line_total REAL NOT NULL,
                         product_id INTEGER REFERENCES products(id), match_method TEXT,
                         match_score REAL);
CREATE TABLE price_observations (id INTEGER PRIMARY KEY, line_item_id INTEGER NOT NULL UNIQUE
                                 REFERENCES line_items(id) ON DELETE CASCADE,
                                 product_id INTEGER NOT NULL REFERENCES products(id),
                                 store_id INTEGER NOT NULL REFERENCES stores(id),
                                 observed_date TEXT NOT NULL, unit_price REAL NOT NULL);
INSERT INTO stores VALUES (1, 'Lidl');
INSERT INTO products VALUES (1, 'banana', 'lb', 'produce');
INSERT INTO aliases VALUES ('bananas', 1, 'user', '2026-06-01T10:00:00');
INSERT INTO receipts VALUES (1, 1, '2026-06-01', 0.69, 'manual', NULL, '2026-06-01T10:00:00');
INSERT INTO line_items VALUES (1, 1, 'BANANAS', 1, 'lb', NULL, 0.69, 0.69, 1, 'alias', 100);
INSERT INTO price_observations VALUES (1, 1, 1, 1, '2026-06-01', 0.69);
"""


def test_reads_a_database_created_before_the_migration(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.close()

    db = PriceDB(path)
    [obs] = db.observations()
    assert (obs.product, obs.store, obs.observed_date, obs.unit_price) == (
        "banana", "Lidl", dt.date(2026, 6, 1), 0.69)
    assert db.receipts()[0]["purchase_date"] == "2026-06-01"
    assert db.aliases() == {"bananas": "banana"}
    db.close()


def test_schema_compiles_for_postgres():
    # No Postgres server in the test run, so this only checks the DDL renders for its dialect.
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    from grocery_optimizer.orm import Base

    ddl = [str(CreateTable(t).compile(dialect=postgresql.dialect()))
           for t in Base.metadata.sorted_tables]
    assert any("CREATE TABLE price_observations" in d for d in ddl)
    assert any("ON DELETE CASCADE" in d for d in ddl)
