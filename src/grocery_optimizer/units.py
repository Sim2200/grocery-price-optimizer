"""Size parsing and comparable unit prices.

Receipts mix pricing styles: bananas at $0.69/lb, a 1 gal jug of milk for
$3.49, a dozen eggs for $2.99, chicken as a 1.5 lb pack. To compare stores
we convert every observation into the canonical product's unit
($/lb, $/oz, $/fl_oz, $/gal or $/each).

Every unit belongs to one *dimension* (weight, volume or count) and has a
factor that converts it into that dimension's base unit (oz, fl_oz, each).
Conversions only happen within a dimension.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import LineItem

# unit -> (dimension, how many base units one of this unit is)
UNIT_FACTORS: dict[str, tuple[str, float]] = {
    # weight, base = oz
    "oz": ("weight", 1.0),
    "lb": ("weight", 16.0),
    "g": ("weight", 0.035274),
    "kg": ("weight", 35.274),
    # volume, base = fl_oz
    "fl_oz": ("volume", 1.0),
    "pt": ("volume", 16.0),
    "qt": ("volume", 32.0),
    "gal": ("volume", 128.0),
    "ml": ("volume", 0.033814),
    "l": ("volume", 33.814),
    # count, base = each
    "each": ("count", 1.0),
    "dozen": ("count", 12.0),
}

# Spellings seen on receipts and labels -> canonical unit name.
UNIT_ALIASES: dict[str, str] = {
    "oz": "oz", "ounce": "oz", "ounces": "oz", "wt oz": "oz", "net wt oz": "oz",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb", "#": "lb",
    "g": "g", "gr": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "fl oz": "fl_oz", "fl. oz": "fl_oz", "fl.oz": "fl_oz", "floz": "fl_oz", "fl_oz": "fl_oz",
    "pt": "pt", "pint": "pt", "pints": "pt",
    "qt": "qt", "quart": "qt", "quarts": "qt",
    "gal": "gal", "gallon": "gal", "gallons": "gal",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "l": "l", "ltr": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "ea": "each", "each": "each", "ct": "each", "count": "each", "pk": "each",
    "pack": "each", "pc": "each", "pcs": "each",
    "dz": "dozen", "doz": "dozen", "dozen": "dozen",
}

# Units a canonical product can be priced in.
COMPARABLE_UNITS = ("lb", "oz", "fl_oz", "gal", "each")


@dataclass(frozen=True)
class Quantity:
    amount: float
    unit: str  # canonical unit name, a key of UNIT_FACTORS

    @property
    def dimension(self) -> str:
        return UNIT_FACTORS[self.unit][0]

    def to(self, target_unit: str) -> float:
        """Express this quantity in `target_unit` (same dimension only)."""
        return self.amount * conversion_factor(self.unit, target_unit)


def normalize_unit(text: str) -> str | None:
    """Map a unit spelling ('lbs', 'fl. oz', 'ct') to its canonical name."""
    cleaned = text.strip().lower().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return UNIT_ALIASES.get(cleaned)


def conversion_factor(from_unit: str, to_unit: str) -> float:
    """How many `to_unit` are in one `from_unit`. Raises if dimensions differ."""
    from_dim, from_base = UNIT_FACTORS[from_unit]
    to_dim, to_base = UNIT_FACTORS[to_unit]
    if from_dim != to_dim:
        raise ValueError(f"Cannot convert {from_unit} ({from_dim}) to {to_unit} ({to_dim})")
    return from_base / to_base


def same_dimension(unit_a: str, unit_b: str) -> bool:
    return UNIT_FACTORS[unit_a][0] == UNIT_FACTORS[unit_b][0]


# Longest spellings first so "fl oz" wins over "oz".
_UNIT_PATTERN = "|".join(
    re.escape(alias) for alias in sorted(UNIT_ALIASES, key=len, reverse=True) if alias != "#"
)
_NUMBER = r"(\d+(?:\.\d+)?|\d+/\d+)"
# Optional "2 x" / "2x" multipack prefix, then a number, then a unit.
SIZE_RE = re.compile(
    rf"(?:(\d+)\s*[xX]\s*)?{_NUMBER}\s*({_UNIT_PATTERN})(?![a-z])",
    re.IGNORECASE,
)


def _to_float(number: str) -> float:
    if "/" in number:
        num, den = number.split("/")
        return float(num) / float(den)
    return float(number)


def parse_size(text: str | None) -> Quantity | None:
    """Parse a package size such as '16 oz', '1/2 gal', '12 ct', '2 x 8oz', 'dozen'.

    Returns None when no size can be found.
    """
    if not text:
        return None
    match = SIZE_RE.search(text)
    if match:
        multiplier = int(match.group(1)) if match.group(1) else 1
        amount = _to_float(match.group(2)) * multiplier
        unit = normalize_unit(match.group(3))
        if unit is not None and amount > 0:
            return Quantity(amount, unit)
    if re.search(r"\b(dozen|doz|dz)\b", text, re.IGNORECASE):
        return Quantity(1.0, "dozen")
    return None


def comparable_unit_price(item: LineItem, target_unit: str) -> float | None:
    """Price of `item` expressed per `target_unit`, or None if not comparable.

    Cases:
    1. Sold by weight/volume (unit='lb', 'kg', ...): convert the per-unit price.
    2. Sold per package (unit='each') with a size: divide by the package size.
       If no explicit size is given, try to find one in the raw name
       (e.g. 'WHOLE MILK 1 GAL').
    3. Sold per package with no size: only comparable when the target is 'each'.
    """
    if target_unit not in UNIT_FACTORS:
        raise ValueError(f"Unknown target unit: {target_unit}")

    if item.unit != "each":
        if not same_dimension(item.unit, target_unit):
            return None
        # $ per item.unit -> $ per target_unit
        return item.unit_price / conversion_factor(item.unit, target_unit)

    size = parse_size(item.size) or parse_size(item.raw_name)
    if size is None:
        return item.unit_price if target_unit == "each" else None
    if not same_dimension(size.unit, target_unit):
        # e.g. an avocado with a weight on the label but priced per each.
        return item.unit_price if target_unit == "each" else None
    package_amount = size.to(target_unit)
    if package_amount <= 0:
        return None
    return item.unit_price / package_amount
