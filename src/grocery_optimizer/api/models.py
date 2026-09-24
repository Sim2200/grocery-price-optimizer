"""Request / response models for the REST API.

These are separate from the core `schemas.py` on purpose: the API shape can
evolve (extra fields for the UI, flattened views) without touching the
receipt schema that the LLM is asked to fill.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from ..schemas import LineItem, Receipt


class Health(BaseModel):
    status: str
    demo_mode: bool
    extractor: str
    model: str


class ProductOut(BaseModel):
    name: str
    unit: str
    category: str


class ProductIn(BaseModel):
    name: str = Field(min_length=1)
    unit: str = Field(description="lb, oz, fl_oz, gal or each")
    category: str = "other"


class Candidate(BaseModel):
    product: str
    score: float


class LineMatch(BaseModel):
    """A receipt line plus the matcher's suggestion, shown in the review table."""

    item: LineItem
    product: str | None
    match_method: str
    match_score: float | None = None
    needs_review: bool = False
    candidates: list[Candidate] = []


class DraftReceipt(BaseModel):
    """An extracted (not yet saved) receipt waiting for user review."""

    store: str
    date: dt.date | None
    total: float | None
    lines: list[LineMatch]
    warnings: list[str] = []
    source: str
    file_name: str | None = None


class CsvIn(BaseModel):
    csv: str


class SaveReceiptIn(BaseModel):
    """The reviewed receipt. Lines the user re-matched should use match_method='user'."""

    store: str
    date: dt.date | None = None
    total: float | None = None
    lines: list[LineMatch] = Field(min_length=1)
    source: str = "manual"
    file_name: str | None = None

    def to_receipt(self) -> Receipt:
        return Receipt(store=self.store, date=self.date, total=self.total,
                       line_items=[line.item for line in self.lines])


class SavedReceipt(BaseModel):
    receipt_id: int


class ReceiptSummary(BaseModel):
    id: int
    store: str
    purchase_date: str | None
    total: float | None
    source: str
    file_name: str | None
    n_items: int
    n_unmatched: int


class LineItemOut(BaseModel):
    id: int
    receipt_id: int
    store: str
    purchase_date: str | None
    raw_name: str
    quantity: float
    unit: str
    size: str | None
    unit_price: float
    line_total: float
    product: str | None
    match_method: str | None
    match_score: float | None
    comparable_price: float | None
    product_unit: str | None


class RematchIn(BaseModel):
    product: str | None
    remember: bool = True


class AliasIn(BaseModel):
    raw_name: str = Field(min_length=1)
    product: str


class AliasOut(BaseModel):
    alias: str
    product: str
    source: str
    updated_at: str


class PriceCell(BaseModel):
    price: float
    n_observations: int
    last_seen: dt.date


class PriceRow(BaseModel):
    product: str
    unit: str
    category: str
    prices: dict[str, PriceCell]  # store -> estimate (stores with no data are absent)
    cheapest_store: str | None


class PriceTable(BaseModel):
    method: str
    stores: list[str]
    rows: list[PriceRow]


class PricePoint(BaseModel):
    store: str
    date: dt.date
    unit_price: float


class WatchIn(BaseModel):
    product: str
    target_price: float = Field(gt=0, description="Alert at or below this price per product unit")


class AlertOut(BaseModel):
    product: str
    store: str
    price: float
    target_price: float
    observed_date: dt.date
    previous_price: float | None


class WatchOut(BaseModel):
    product: str
    unit: str
    target_price: float
    best_price: float | None = Field(description="Lowest latest price across stores")
    best_store: str | None
    alerts: list[AlertOut]


class Amount(BaseModel):
    label: str
    amount: float


class TripReplayOut(BaseModel):
    receipt_id: int
    store: str
    date: dt.date
    actual: float
    optimal: float
    saved: float
    stores_in_plan: list[str]


class Insights(BaseModel):
    total_spend: float
    receipts: int
    by_store: list[Amount]
    by_category: list[Amount]
    by_month: list[Amount]
    trip_cost: float
    actual_total: float = Field(description="Paid for the comparable lines + one trip per receipt")
    optimal_total: float = Field(description="The optimizer's plans for the same items")
    estimated_savings: float
    estimated_savings_percent: float
    trips: list[TripReplayOut]


class AssistIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000,
                      description='A recipe, a dish ("tacos for 4") or a free-text list')


class AssistLine(BaseModel):
    request: str
    product: str | None
    quantity: float
    unit: str
    note: str


class AssistOut(BaseModel):
    source: str
    lines: list[AssistLine]
    notes: list[str]


class ShoppingItem(BaseModel):
    product: str
    quantity: float = Field(gt=0)


class PlanIn(BaseModel):
    items: list[ShoppingItem] = Field(min_length=1)
    stores: list[str] | None = Field(default=None, description="Stores you are willing to visit (default: all)")
    trip_cost: float = Field(default=5.0, ge=0, description="Cost of visiting one store, in dollars")
    trip_costs: dict[str, float] | None = Field(default=None, description="Per-store override of trip_cost")
    max_stores: int | None = Field(default=None, ge=1)
    price_method: str = Field(default="weighted", pattern="^(weighted|latest)$")


class PlanLine(BaseModel):
    product: str
    quantity: float
    unit: str
    unit_price: float
    cost: float


class StoreStop(BaseModel):
    store: str
    trip_cost: float
    items: list[PlanLine]
    subtotal: float


class PlanOut(BaseModel):
    name: str
    status: str
    total: float
    items_total: float
    trips_total: float
    stops: list[StoreStop]


class Savings(BaseModel):
    amount: float
    percent: float


class PlanResult(BaseModel):
    optimal: PlanOut
    single_store: PlanOut | None
    greedy: PlanOut
    single_store_candidates: dict[str, float]
    savings_vs_single_store: Savings | None
    unavailable: list[str]


class DemoLoadIn(BaseModel):
    reset: bool = True


class DemoLoadOut(BaseModel):
    receipts_loaded: int
