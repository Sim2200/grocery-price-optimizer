"""Pydantic models for receipts, plus the JSON schema sent to the LLM.

The same shape is used by every ingestion path (LLM extraction, CSV /
form entry, and the bundled synthetic demo data), so everything downstream
only ever sees a validated `Receipt`.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Units a receipt line can be sold in. "each" means per package / per piece.
ReceiptUnit = Literal["each", "lb", "oz", "kg", "g", "gal", "qt", "pt", "fl_oz", "l", "ml"]
RECEIPT_UNITS: tuple[str, ...] = ReceiptUnit.__args__  # type: ignore[attr-defined]


class LineItem(BaseModel):
    """One purchased item as printed on the receipt."""

    raw_name: str = Field(min_length=1, description="Item text exactly as printed")
    quantity: float = Field(gt=0, description="Count of packages, or weight/volume if sold by weight")
    unit: ReceiptUnit = Field(description="Unit that `quantity` and `unit_price` refer to")
    size: str | None = Field(default=None, description="Package size if printed, e.g. '16 oz' or '1 gal'")
    unit_price: float = Field(ge=0, description="Price per `unit`")
    line_total: float = Field(description="Amount charged for this line (after item-level discounts)")

    @field_validator("raw_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return value.strip()


class Receipt(BaseModel):
    """A whole receipt."""

    store: str = Field(min_length=1)
    date: dt.date | None = None
    line_items: list[LineItem] = Field(min_length=1)
    total: float | None = Field(default=None, description="Grand total printed on the receipt")

    def items_sum(self) -> float:
        return round(sum(item.line_total for item in self.line_items), 2)


def consistency_warnings(receipt: Receipt, tolerance: float = 0.02) -> list[str]:
    """Soft arithmetic checks shown to the user during review.

    These are warnings, not validation errors: real receipts have coupons,
    tax and deposits, so a mismatch is a hint to double-check, not proof
    of a bad extraction.
    """
    warnings: list[str] = []
    for i, item in enumerate(receipt.line_items):
        expected = round(item.quantity * item.unit_price, 2)
        if abs(expected - item.line_total) > tolerance + 0.01 * abs(expected):
            warnings.append(
                f"Line {i + 1} '{item.raw_name}': {item.quantity} x {item.unit_price:.2f} = "
                f"{expected:.2f}, but line_total is {item.line_total:.2f}"
            )
    if receipt.total is not None and abs(receipt.items_sum() - receipt.total) > tolerance:
        warnings.append(
            f"Line items sum to {receipt.items_sum():.2f} but the receipt total is "
            f"{receipt.total:.2f} (tax, deposits or a missed line?)"
        )
    return warnings


def _nullable(json_type: str) -> dict:
    return {"anyOf": [{"type": json_type}, {"type": "null"}]}


# Hand-written JSON schema for LLM structured outputs. It mirrors the
# Pydantic models above (a unit test checks the field names stay in sync).
# Structured outputs require every property to be listed in `required` and
# `additionalProperties: false`; optional values are expressed as nullable.
RECEIPT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "store": {"type": "string", "description": "Store / chain name, e.g. 'Trader Joe's'"},
        "date": {**_nullable("string"), "description": "Purchase date as YYYY-MM-DD, or null"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_name": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string", "enum": list(RECEIPT_UNITS)},
                    "size": _nullable("string"),
                    "unit_price": {"type": "number"},
                    "line_total": {"type": "number"},
                },
                "required": ["raw_name", "quantity", "unit", "size", "unit_price", "line_total"],
                "additionalProperties": False,
            },
        },
        "total": _nullable("number"),
    },
    "required": ["store", "date", "line_items", "total"],
    "additionalProperties": False,
}
