"""SQLAlchemy 2.0 ORM models: one class per table.

The same models work on SQLite (the default, a single local file) and on
Postgres (set DATABASE_URL). `Mapped[...]` type hints tell SQLAlchemy the
column type and whether it is nullable (`X | None` means NULL is allowed).

Tables
------
stores              one row per store (chain) name
products            canonical products and the unit their price is compared in
aliases             raw receipt name -> product (user corrections + confirmed matches)
receipts            one row per receipt (store, date, printed total, source)
line_items          every receipt line exactly as extracted, plus its product match
price_observations  comparable unit price ($/unit of the product) per line item
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class StoreRow(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)


class ProductRow(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    unit: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(50), default="other")


class AliasRow(Base):
    __tablename__ = "aliases"

    alias: Mapped[str] = mapped_column(String(300), primary_key=True)  # normalize_alias_key(raw_name)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(20))  # 'user' | 'fuzzy' | 'llm'
    updated_at: Mapped[str] = mapped_column(String(32))  # ISO-8601 text

    product: Mapped[ProductRow] = relationship()


class ReceiptRow(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    purchase_date: Mapped[dt.date | None] = mapped_column(Date)
    total: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20))  # 'llm' | 'manual' | 'demo'
    file_name: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[str] = mapped_column(String(32))

    store: Mapped[StoreRow] = relationship()
    # Deleting a receipt deletes its lines (and, through them, their price observations).
    line_items: Mapped[list[LineItemRow]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", passive_deletes=True)


class LineItemRow(Base):
    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"))
    raw_name: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    size: Mapped[str | None] = mapped_column(String(50))
    unit_price: Mapped[float] = mapped_column(Float)
    line_total: Mapped[float] = mapped_column(Float)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    match_method: Mapped[str | None] = mapped_column(String(20))
    match_score: Mapped[float | None] = mapped_column(Float)

    receipt: Mapped[ReceiptRow] = relationship(back_populates="line_items")
    product: Mapped[ProductRow | None] = relationship()
    observation: Mapped[PriceObservationRow | None] = relationship(
        back_populates="line_item", cascade="all, delete-orphan", passive_deletes=True)


class PriceObservationRow(Base):
    __tablename__ = "price_observations"
    __table_args__ = (Index("idx_obs_product_store", "product_id", "store_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_item_id: Mapped[int] = mapped_column(
        ForeignKey("line_items.id", ondelete="CASCADE"), unique=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    observed_date: Mapped[dt.date] = mapped_column(Date)
    unit_price: Mapped[float] = mapped_column(Float)  # $ per products.unit

    line_item: Mapped[LineItemRow] = relationship(back_populates="observation")
    product: Mapped[ProductRow] = relationship()
    store: Mapped[StoreRow] = relationship()

