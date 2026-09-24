"""Price database (SQLAlchemy 2.0 ORM).

`PriceDB` is a small repository class: the rest of the app calls methods like
`insert_receipt` or `observations()` and never writes SQL itself. The tables
are defined in `orm.py`.

Which database?
- a file path such as `data/grocery.db`   -> SQLite file (the default)
- `:memory:`                              -> throwaway SQLite database (tests)
- a URL such as `postgresql+psycopg://user:pass@host/db` -> Postgres
  (set the DATABASE_URL environment variable; see config.py)

Raw line items are kept separately from price observations so a user
correction (re-matching a line) can simply recompute its observation.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, case, create_engine, delete, event, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from .catalog import Product
from .matching import MatchResult, normalize_alias_key
from .orm import (
    AliasRow,
    Base,
    LineItemRow,
    PriceObservationRow,
    ProductRow,
    ReceiptRow,
    StoreRow,
    WatchRow,
)
from .schemas import LineItem, Receipt
from .units import comparable_unit_price


@dataclass(frozen=True)
class Observation:
    product: str
    store: str
    observed_date: dt.date
    unit_price: float
    unit: str


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def database_url(target: str | Path) -> str:
    """Turn a file path into a SQLite URL; pass real URLs (anything with '://') through."""
    target = str(target)
    if "://" in target:
        return target
    if target == ":memory:":
        return "sqlite://"
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{target}"


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    # SQLite ignores foreign keys (and ON DELETE CASCADE) unless this is set per connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def _new_engine(url: str) -> Engine:
    if url == "sqlite://":
        # In-memory: every connection must share the one database, so use a single connection.
        engine = create_engine(url, poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
    elif url.startswith("sqlite"):
        # FastAPI runs sync endpoints in a thread pool, so connections cross threads.
        engine = create_engine(url, connect_args={"check_same_thread": False})
    else:
        # pool_pre_ping drops connections the server closed (e.g. after a Postgres restart).
        engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    Base.metadata.create_all(engine)  # CREATE TABLE IF NOT EXISTS for every model
    return engine


@lru_cache(maxsize=None)
def _shared_engine(url: str) -> Engine:
    """One engine (and connection pool) per database URL for the whole process."""
    return _new_engine(url)


class PriceDB:
    """One `PriceDB` = one SQLAlchemy session. The API opens one per request."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.url = database_url(path)
        self.path = str(path)
        # A fresh in-memory database per PriceDB (tests rely on this); files and servers share.
        self._owns_engine = self.url == "sqlite://"
        self.engine = _new_engine(self.url) if self._owns_engine else _shared_engine(self.url)
        # expire_on_commit=False: objects stay readable after commit without another query.
        self.session = Session(self.engine, expire_on_commit=False)

    def close(self) -> None:
        self.session.close()
        if self._owns_engine:
            self.engine.dispose()

    def ping(self) -> None:
        """Raise if the database can't run a trivial query (used by the readiness probe)."""
        self.session.execute(text("SELECT 1"))

    def reset_data(self) -> None:
        """Delete all receipts, prices, aliases and stores (products and the watchlist are kept)."""
        for model in (PriceObservationRow, LineItemRow, ReceiptRow, AliasRow, StoreRow):
            self.session.execute(delete(model))
        self.session.commit()

    # ----- stores & products ---------------------------------------------
    def _store(self, name: str) -> StoreRow:
        store = self.session.scalar(select(StoreRow).where(StoreRow.name == name))
        if store is None:
            store = StoreRow(name=name)
            self.session.add(store)
            self.session.flush()  # assigns store.id without committing
        return store

    def upsert_store(self, name: str) -> int:
        store = self._store(name)
        self.session.commit()
        return store.id

    def store_names(self) -> list[str]:
        return list(self.session.scalars(select(StoreRow.name).order_by(StoreRow.name)))

    def add_product(self, product: Product) -> int:
        row = self.session.scalar(select(ProductRow).where(ProductRow.name == product.name))
        if row is None:
            row = ProductRow(name=product.name, unit=product.unit, category=product.category)
            self.session.add(row)
            self.session.commit()
        return row.id

    def sync_catalog(self, catalog: Iterable[Product]) -> None:
        existing = set(self.session.scalars(select(ProductRow.name)))
        for product in catalog:
            if product.name not in existing:
                self.session.add(ProductRow(name=product.name, unit=product.unit,
                                            category=product.category))
        self.session.commit()

    def products(self) -> list[Product]:
        rows = self.session.scalars(select(ProductRow).order_by(ProductRow.name))
        return [Product(r.name, r.unit, r.category) for r in rows]

    def _product(self, name: str) -> ProductRow:
        row = self.session.scalar(select(ProductRow).where(ProductRow.name == name))
        if row is None:
            raise KeyError(f"Unknown product: {name}")
        return row

    def _product_id(self, name: str) -> int:
        return self._product(name).id

    # ----- aliases -----------------------------------------------------------
    def set_alias(self, raw_name: str, product_name: str, source: str = "user") -> None:
        """Remember raw_name -> product. A 'user' alias is never overwritten by automation."""
        key = normalize_alias_key(raw_name)
        product_id = self._product_id(product_name)
        row = self.session.get(AliasRow, key)
        if row is None:
            self.session.add(AliasRow(alias=key, product_id=product_id, source=source,
                                      updated_at=_now()))
        elif row.source == "user" and source != "user":
            return
        else:
            row.product_id, row.source, row.updated_at = product_id, source, _now()
        self.session.commit()

    def _alias_query(self):
        return (select(AliasRow.alias, ProductRow.name.label("product"), AliasRow.source,
                       AliasRow.updated_at)
                .join(ProductRow, ProductRow.id == AliasRow.product_id)
                .order_by(AliasRow.alias))

    def aliases(self) -> dict[str, str]:
        return {r.alias: r.product for r in self.session.execute(self._alias_query())}

    def alias_rows(self) -> list[dict]:
        return [dict(r._mapping) for r in self.session.execute(self._alias_query())]

    def delete_alias(self, alias: str) -> None:
        self.session.execute(delete(AliasRow).where(AliasRow.alias == alias))
        self.session.commit()

    # ----- watchlist ---------------------------------------------------------
    def set_watch(self, product_name: str, target_price: float) -> None:
        """Watch a product (or change its target price)."""
        product = self._product(product_name)
        row = self.session.scalar(select(WatchRow).where(WatchRow.product_id == product.id))
        if row is None:
            self.session.add(WatchRow(product=product, target_price=target_price,
                                      created_at=_now()))
        else:
            row.target_price = target_price
        self.session.commit()

    def delete_watch(self, product_name: str) -> None:
        product = self._product(product_name)
        self.session.execute(delete(WatchRow).where(WatchRow.product_id == product.id))
        self.session.commit()

    def watchlist(self) -> dict[str, float]:
        """product name -> target price, sorted by product name."""
        query = (select(ProductRow.name, WatchRow.target_price)
                 .join(ProductRow, ProductRow.id == WatchRow.product_id)
                 .order_by(ProductRow.name))
        return {name: target for name, target in self.session.execute(query)}

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
        row = ReceiptRow(
            store=self._store(receipt.store),
            purchase_date=receipt.date or dt.date.today(),
            total=receipt.total, source=source, file_name=file_name, created_at=_now(),
        )
        for item, match in zip(receipt.line_items, matches, strict=True):
            line = LineItemRow(
                raw_name=item.raw_name, quantity=item.quantity, unit=item.unit, size=item.size,
                unit_price=item.unit_price, line_total=item.line_total,
                product=self._product(match.product) if match.product else None,
                match_method=match.method, match_score=match.score,
            )
            line.observation = self._observation_for(line, row)
            row.line_items.append(line)
        self.session.add(row)
        self.session.commit()
        return row.id

    def _observation_for(self, line: LineItemRow, receipt: ReceiptRow) -> PriceObservationRow | None:
        """The comparable price observation for one line, or None if it can't be compared."""
        if line.product is None:
            return None
        item = LineItem(raw_name=line.raw_name, quantity=line.quantity, unit=line.unit,
                        size=line.size, unit_price=line.unit_price, line_total=line.line_total)
        price = comparable_unit_price(item, line.product.unit)
        if price is None:
            return None  # e.g. sold per each with no size, but the product is priced per lb
        return PriceObservationRow(product=line.product, store=receipt.store,
                                   observed_date=receipt.purchase_date or dt.date.today(),
                                   unit_price=price)

    def rematch_line_item(self, line_item_id: int, product_name: str | None,
                          remember: bool = True) -> None:
        """User correction: point a line at another product (or none) and
        optionally save the raw name as a 'user' alias."""
        product = self._product(product_name) if product_name else None
        line = self.session.get(LineItemRow, line_item_id)
        if line is None:
            return
        line.product, line.match_method, line.match_score = product, "user", 100.0
        if line.observation is not None:
            line.observation = None
            self.session.flush()  # delete-orphan cascade: the old observation row is deleted
        line.observation = self._observation_for(line, line.receipt)
        self.session.commit()
        if remember and product_name:
            self.set_alias(line.raw_name, product_name, source="user")

    def delete_receipt(self, receipt_id: int) -> None:
        row = self.session.get(ReceiptRow, receipt_id)
        if row is not None:
            self.session.delete(row)  # cascades to line items and observations
            self.session.commit()

    def receipts(self) -> list[dict]:
        n_unmatched = func.coalesce(
            func.sum(case((LineItemRow.id.is_not(None) & LineItemRow.product_id.is_(None), 1),
                          else_=0)), 0)
        query = (
            select(ReceiptRow, StoreRow.name.label("store"),
                   func.count(LineItemRow.id).label("n_items"), n_unmatched.label("n_unmatched"))
            .join(StoreRow, StoreRow.id == ReceiptRow.store_id)
            .outerjoin(LineItemRow, LineItemRow.receipt_id == ReceiptRow.id)
            .group_by(ReceiptRow.id, StoreRow.name)
            .order_by(ReceiptRow.purchase_date.desc(), ReceiptRow.id.desc())
        )
        return [
            {"id": r.id, "store": store,
             "purchase_date": r.purchase_date.isoformat() if r.purchase_date else None,
             "total": r.total, "source": r.source, "file_name": r.file_name,
             "n_items": int(n_items), "n_unmatched": int(unmatched)}
            for r, store, n_items, unmatched in self.session.execute(query)
        ]

    def line_items(self, receipt_id: int | None = None, only_unmatched: bool = False) -> list[dict]:
        query = (
            select(LineItemRow, ReceiptRow.purchase_date, StoreRow.name.label("store"),
                   ProductRow.name.label("product"), ProductRow.unit.label("product_unit"),
                   PriceObservationRow.unit_price.label("comparable_price"))
            .join(ReceiptRow, ReceiptRow.id == LineItemRow.receipt_id)
            .join(StoreRow, StoreRow.id == ReceiptRow.store_id)
            .outerjoin(ProductRow, ProductRow.id == LineItemRow.product_id)
            .outerjoin(PriceObservationRow, PriceObservationRow.line_item_id == LineItemRow.id)
            .order_by(ReceiptRow.purchase_date.desc(), LineItemRow.id)
        )
        if receipt_id is not None:
            query = query.where(LineItemRow.receipt_id == receipt_id)
        if only_unmatched:
            query = query.where(LineItemRow.product_id.is_(None))
        return [
            {"id": li.id, "receipt_id": li.receipt_id, "store": store,
             "purchase_date": date.isoformat() if date else None, "raw_name": li.raw_name,
             "quantity": li.quantity, "unit": li.unit, "size": li.size,
             "unit_price": li.unit_price, "line_total": li.line_total, "product": product,
             "match_method": li.match_method, "match_score": li.match_score,
             "comparable_price": comparable, "product_unit": product_unit}
            for li, date, store, product, product_unit, comparable in self.session.execute(query)
        ]

    # ----- prices ------------------------------------------------------------
    def observations(self) -> list[Observation]:
        query = (
            select(ProductRow.name, ProductRow.unit, StoreRow.name,
                   PriceObservationRow.observed_date, PriceObservationRow.unit_price)
            .join(ProductRow, ProductRow.id == PriceObservationRow.product_id)
            .join(StoreRow, StoreRow.id == PriceObservationRow.store_id)
            .order_by(PriceObservationRow.observed_date, PriceObservationRow.id)
        )
        return [Observation(product, store, date, price, unit)
                for product, unit, store, date, price in self.session.execute(query)]
