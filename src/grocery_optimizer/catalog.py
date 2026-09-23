"""Canonical product catalog.

A canonical product is the thing we compare across stores, e.g.
"banana (organic)" priced per lb. Receipt lines are matched onto these.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import CATALOG_PATH
from .units import COMPARABLE_UNITS


@dataclass(frozen=True)
class Product:
    name: str
    unit: str  # one of COMPARABLE_UNITS
    category: str = "other"
    synonyms: tuple[str, ...] = field(default_factory=tuple)

    @property
    def organic(self) -> bool:
        return "organic" in self.name.lower()

    def __post_init__(self) -> None:
        if self.unit not in COMPARABLE_UNITS:
            raise ValueError(f"{self.name}: unit must be one of {COMPARABLE_UNITS}, got {self.unit!r}")


def load_catalog(path: Path = CATALOG_PATH) -> list[Product]:
    data = json.loads(Path(path).read_text())
    return [
        Product(
            name=p["name"],
            unit=p["unit"],
            category=p.get("category", "other"),
            synonyms=tuple(p.get("synonyms", [])),
        )
        for p in data["products"]
    ]
