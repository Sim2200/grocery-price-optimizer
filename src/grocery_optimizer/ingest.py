"""Glue between extraction, matching and the database.

    Receipt --match_receipt--> [MatchResult] --(user review)--> save_receipt --> PriceDB
"""

from __future__ import annotations

import re
import string
from pathlib import Path

from rapidfuzz import fuzz

from .catalog import Product, load_catalog
from .config import SYNTHETIC_RECEIPTS_DIR, has_api_key
from .db import PriceDB
from .extraction import parse_receipt_json
from .matching import MatchResult, ProductMatcher
from .schemas import Receipt

STORE_MATCH_THRESHOLD = 88.0


def canonical_store_name(raw: str, known_stores: list[str]) -> str:
    """'TRADER JOE'S #552' -> "Trader Joe's" (reusing an existing store name if close)."""
    cleaned = re.sub(r"(#\s*\d+|store\s*\d+|\d{3,})", " ", raw, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.split()).strip(" -,")
    for store in known_stores:
        if fuzz.ratio(cleaned.lower(), store.lower()) >= STORE_MATCH_THRESHOLD:
            return store
    return string.capwords(cleaned.lower()) if cleaned.isupper() else cleaned


def build_matcher(db: PriceDB, use_llm: bool = False) -> ProductMatcher:
    """Matcher over the bundled catalog (with synonyms) plus user-added products."""
    catalog = load_catalog()
    known = {p.name for p in catalog}
    extra = [p for p in db.products() if p.name not in known]
    llm = None
    if use_llm and has_api_key():
        from .llm_matching import LLMMatchFallback  # imported lazily: optional feature
        llm = LLMMatchFallback()
    return ProductMatcher(catalog + extra, aliases=db.aliases(), llm_fallback=llm)


def match_receipt(receipt: Receipt, matcher: ProductMatcher) -> list[MatchResult]:
    return [matcher.match(item.raw_name) for item in receipt.line_items]


def save_receipt(
    db: PriceDB,
    receipt: Receipt,
    matches: list[MatchResult],
    source: str,
    file_name: str | None = None,
) -> int:
    """Persist a reviewed receipt. Lines the user matched by hand
    (method == 'user') are remembered in the alias table."""
    store = canonical_store_name(receipt.store, db.store_names())
    receipt = receipt.model_copy(update={"store": store})
    receipt_id = db.insert_receipt(receipt, matches, source=source, file_name=file_name)
    for item, match in zip(receipt.line_items, matches, strict=True):
        if match.method == "user" and match.product:
            db.set_alias(item.raw_name, match.product, source="user")
    return receipt_id


def ingest_receipt(db: PriceDB, receipt: Receipt, source: str, file_name: str | None = None,
                   matcher: ProductMatcher | None = None) -> tuple[int, list[MatchResult]]:
    """Match and save in one step (no human review), used by the CLI and demo loader."""
    matcher = matcher or build_matcher(db)
    matches = match_receipt(receipt, matcher)
    return save_receipt(db, receipt, matches, source, file_name), matches


def open_db(path: str | Path) -> PriceDB:
    """Open (or create) a database and make sure the catalog products exist."""
    db = PriceDB(path)
    db.sync_catalog(load_catalog())
    return db


def load_demo_data(db: PriceDB, receipts_dir: Path = SYNTHETIC_RECEIPTS_DIR) -> int:
    """Load every bundled SYNTHETIC receipt JSON into the database."""
    files = sorted(Path(receipts_dir).glob("SYNTHETIC_*.json"))
    matcher = build_matcher(db)
    for path in files:
        receipt = parse_receipt_json(path.read_text())
        ingest_receipt(db, receipt, source="demo", file_name=path.name, matcher=matcher)
    return len(files)


def add_custom_product(db: PriceDB, name: str, unit: str, category: str = "other") -> Product:
    product = Product(name=name.strip(), unit=unit, category=category)
    db.add_product(product)
    return product
