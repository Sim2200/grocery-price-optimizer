"""SQLite price database.

Tables
------
stores              one row per store (chain) name
products            canonical products and the unit their price is compared in
aliases             raw receipt name -> product (user corrections + confirmed matches)
receipts            one row per receipt (store, date, printed total, source)
line_items          every receipt line exactly as extracted, plus its product match
price_observations  comparable unit price ($/unit of the product) per line item

Raw line items are kept separately from price observations so a user
correction (re-matching a line) can simply recompute its observation.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .catalog import Product
from .matching import MatchResult, normalize_alias_key
from .schemas import LineItem, Receipt
from .units import comparable_unit_price

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS products (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    unit     TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other'
);
CREATE TABLE IF NOT EXISTS aliases (
    alias      TEXT PRIMARY KEY,           -- normalize_alias_key(raw_name)
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,              -- 'user' | 'fuzzy' | 'llm'
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    id            INTEGER PRIMARY KEY,
    store_id      INTEGER NOT NULL REFERENCES stores(id),
    purchase_date TEXT,
    total         REAL,
    source        TEXT NOT NULL,           -- 'llm' | 'manual' | 'demo'
    file_name     TEXT,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS line_items (
    id           INTEGER PRIMARY KEY,
    receipt_id   INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    raw_name     TEXT NOT NULL,
    quantity     REAL NOT NULL,
    unit         TEXT NOT NULL,
    size         TEXT,
    unit_price   REAL NOT NULL,
    line_total   REAL NOT NULL,
    product_id   INTEGER REFERENCES products(id),
    match_method TEXT,
    match_score  REAL
);
CREATE TABLE IF NOT EXISTS price_observations (
    id            INTEGER PRIMARY KEY,
    line_item_id  INTEGER NOT NULL UNIQUE REFERENCES line_items(id) ON DELETE CASCADE,
    product_id    INTEGER NOT NULL REFERENCES products(id),
    store_id      INTEGER NOT NULL REFERENCES stores(id),
    observed_date TEXT NOT NULL,
    unit_price    REAL NOT NULL            -- $ per products.unit
);
CREATE INDEX IF NOT EXISTS idx_obs_product_store ON price_observations(product_id, store_id);
"""


@dataclass(frozen=True)
class Observation:
    product: str
    store: str
    observed_date: dt.date
    unit_price: float
    unit: str


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class PriceDB:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # FastAPI runs sync endpoints in a thread pool; the API opens one connection per request.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def reset_data(self) -> None:
        """Delete all receipts, prices, aliases and stores (products are kept)."""
        for table in ("price_observations", "line_items", "receipts", "aliases", "stores"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()

    # ----- stores & products ---------------------------------------------
    def upsert_store(self, name: str) -> int:
        self.conn.execute("INSERT OR IGNORE INTO stores(name) VALUES (?)", (name,))
        row = self.conn.execute("SELECT id FROM stores WHERE name = ?", (name,)).fetchone()
        return int(row["id"])

    def store_names(self) -> list[str]:
        return [r["name"] for r in self.conn.execute("SELECT name FROM stores ORDER BY name")]

    def add_product(self, product: Product) -> int:
        self.conn.execute(
            "INSERT OR IGNORE INTO products(name, unit, category) VALUES (?, ?, ?)",
            (product.name, product.unit, product.category),
        )
        self.conn.commit()
        return self._product_id(product.name)

    def sync_catalog(self, catalog: Iterable[Product]) -> None:
        for product in catalog:
            self.add_product(product)

    def products(self) -> list[Product]:
        rows = self.conn.execute("SELECT name, unit, category FROM products ORDER BY name")
        return [Product(r["name"], r["unit"], r["category"]) for r in rows]

    def _product_id(self, name: str) -> int:
        row = self.conn.execute("SELECT id FROM products WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown product: {name}")
        return int(row["id"])

    def _product_unit(self, product_id: int) -> str:
        row = self.conn.execute("SELECT unit FROM products WHERE id = ?", (product_id,)).fetchone()
        return str(row["unit"])

    # ----- aliases -----------------------------------------------------------
    def set_alias(self, raw_name: str, product_name: str, source: str = "user") -> None:
        """Remember raw_name -> product. A 'user' alias is never overwritten by automation."""
        key = normalize_alias_key(raw_name)
        existing = self.conn.execute("SELECT source FROM aliases WHERE alias = ?", (key,)).fetchone()
        if existing is not None and existing["source"] == "user" and source != "user":
            return
        self.conn.execute(
            "INSERT INTO aliases(alias, product_id, source, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(alias) DO UPDATE SET product_id = excluded.product_id, "
            "source = excluded.source, updated_at = excluded.updated_at",
            (key, self._product_id(product_name), source, _now()),
        )
        self.conn.commit()

    def aliases(self) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT a.alias, p.name FROM aliases a JOIN products p ON p.id = a.product_id"
        )
        return {r["alias"]: r["name"] for r in rows}

    def alias_rows(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT a.alias, p.name AS product, a.source, a.updated_at "
            "FROM aliases a JOIN products p ON p.id = a.product_id ORDER BY a.alias"
        )
        return [dict(r) for r in rows]

    def delete_alias(self, alias: str) -> None:
        self.conn.execute("DELETE FROM aliases WHERE alias = ?", (alias,))
        self.conn.commit()

    # ----- receipts ----------------------------------------------------------
    def insert_receipt(
        self,
        receipt: Receipt,
        matches: list[MatchResult],
        source: str,
        file_name: str | None = None,
    ) -> int:
        """Store a receipt, its line items and a price observation per matched line."""
        if len(matches) != len(receipt.line_items):
            raise ValueError("Need exactly one match result per line item")
        store_id = self.upsert_store(receipt.store)
        purchase_date = (receipt.date or dt.date.today()).isoformat()
        cur = self.conn.execute(
            "INSERT INTO receipts(store_id, purchase_date, total, source, file_name, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (store_id, purchase_date, receipt.total, source, file_name, _now()),
        )
        receipt_id = int(cur.lastrowid)
        for item, match in zip(receipt.line_items, matches, strict=True):
            product_id = self._product_id(match.product) if match.product else None
            cur = self.conn.execute(
                "INSERT INTO line_items(receipt_id, raw_name, quantity, unit, size, unit_price, "
                "line_total, product_id, match_method, match_score) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (receipt_id, item.raw_name, item.quantity, item.unit, item.size, item.unit_price,
                 item.line_total, product_id, match.method, match.score),
            )
            self._write_observation(int(cur.lastrowid))
        self.conn.commit()
        return receipt_id

    def _write_observation(self, line_item_id: int) -> None:
        """(Re)compute the comparable price observation for one line item."""
        self.conn.execute("DELETE FROM price_observations WHERE line_item_id = ?", (line_item_id,))
        row = self.conn.execute(
            "SELECT li.*, r.store_id, r.purchase_date FROM line_items li "
            "JOIN receipts r ON r.id = li.receipt_id WHERE li.id = ?",
            (line_item_id,),
        ).fetchone()
        if row is None or row["product_id"] is None:
            return
        item = LineItem(
            raw_name=row["raw_name"], quantity=row["quantity"], unit=row["unit"],
            size=row["size"], unit_price=row["unit_price"], line_total=row["line_total"],
        )
        price = comparable_unit_price(item, self._product_unit(row["product_id"]))
        if price is None:
            return  # e.g. sold per each with no size, but the product is priced per lb
        self.conn.execute(
            "INSERT INTO price_observations(line_item_id, product_id, store_id, observed_date, "
            "unit_price) VALUES (?, ?, ?, ?, ?)",
            (line_item_id, row["product_id"], row["store_id"], row["purchase_date"], price),
        )

    def rematch_line_item(self, line_item_id: int, product_name: str | None,
                          remember: bool = True) -> None:
        """User correction: point a line at another product (or none) and
        optionally save the raw name as a 'user' alias."""
        product_id = self._product_id(product_name) if product_name else None
        self.conn.execute(
            "UPDATE line_items SET product_id = ?, match_method = 'user', match_score = 100 "
            "WHERE id = ?",
            (product_id, line_item_id),
        )
        self._write_observation(line_item_id)
        if remember and product_name:
            raw = self.conn.execute(
                "SELECT raw_name FROM line_items WHERE id = ?", (line_item_id,)
            ).fetchone()["raw_name"]
            self.set_alias(raw, product_name, source="user")
        self.conn.commit()

    def delete_receipt(self, receipt_id: int) -> None:
        self.conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
        self.conn.commit()

    def receipts(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT r.id, s.name AS store, r.purchase_date, r.total, r.source, r.file_name, "
            "COUNT(li.id) AS n_items, "
            "SUM(CASE WHEN li.product_id IS NULL THEN 1 ELSE 0 END) AS n_unmatched "
            "FROM receipts r JOIN stores s ON s.id = r.store_id "
            "LEFT JOIN line_items li ON li.receipt_id = r.id "
            "GROUP BY r.id ORDER BY r.purchase_date DESC, r.id DESC"
        )
        return [dict(r) for r in rows]

    def line_items(self, receipt_id: int | None = None, only_unmatched: bool = False) -> list[dict]:
        sql = (
            "SELECT li.id, li.receipt_id, s.name AS store, r.purchase_date, li.raw_name, "
            "li.quantity, li.unit, li.size, li.unit_price, li.line_total, p.name AS product, "
            "li.match_method, li.match_score, po.unit_price AS comparable_price, p.unit AS product_unit "
            "FROM line_items li JOIN receipts r ON r.id = li.receipt_id "
            "JOIN stores s ON s.id = r.store_id "
            "LEFT JOIN products p ON p.id = li.product_id "
            "LEFT JOIN price_observations po ON po.line_item_id = li.id WHERE 1=1"
        )
        params: list = []
        if receipt_id is not None:
            sql += " AND li.receipt_id = ?"
            params.append(receipt_id)
        if only_unmatched:
            sql += " AND li.product_id IS NULL"
        sql += " ORDER BY r.purchase_date DESC, li.id"
        return [dict(r) for r in self.conn.execute(sql, params)]

    # ----- prices ------------------------------------------------------------
    def observations(self) -> list[Observation]:
        rows = self.conn.execute(
            "SELECT p.name AS product, p.unit, s.name AS store, po.observed_date, po.unit_price "
            "FROM price_observations po JOIN products p ON p.id = po.product_id "
            "JOIN stores s ON s.id = po.store_id ORDER BY po.observed_date"
        )
        return [
            Observation(r["product"], r["store"], dt.date.fromisoformat(r["observed_date"]),
                        r["unit_price"], r["unit"])
            for r in rows
        ]
