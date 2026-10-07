"""Product search for the frontend typeahead.

Two passes over the catalog, both cheap enough to run on every (debounced) keystroke:

1. Prefix  - the query is the start of the product name (score 100) or of any word in
             its name or synonyms (score 95). This is what people expect while typing.
2. Fuzzy   - otherwise, the best rapidfuzz score against the name and synonyms, so
             typos ("bananna") and receipt-style words still find something. Uses the
             matcher's `similarity` plus `partial_ratio`, which handles a short query
             against a longer name ("chedd" vs "cheddar cheese").

Results below FUZZY_MIN are dropped, so a query of random letters returns nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .catalog import Product
from .matching import similarity

FUZZY_MIN = 78.0  # minimum fuzzy score (0-100) to show a suggestion


@dataclass(frozen=True)
class SearchHit:
    product: Product
    score: float
    match: str  # "prefix" or "fuzzy"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9% ]+", " ", text.lower())).strip()


def search_products(catalog: list[Product], query: str, limit: int = 8) -> list[SearchHit]:
    q = _norm(query)
    if not q:
        return []
    hits: list[SearchHit] = []
    for product in catalog:
        names = [_norm(n) for n in (product.name, *product.synonyms)]
        if names[0].startswith(q):
            hits.append(SearchHit(product, 100.0, "prefix"))
        elif any(word.startswith(q) for n in names for word in n.split()) or any(n.startswith(q) for n in names):
            hits.append(SearchHit(product, 95.0, "prefix"))
        elif len(q) >= 4:  # short queries fuzzy-match almost everything, so prefix only
            best = max(max(similarity(q, n), fuzz.partial_ratio(q, n)) for n in names)
            if best >= FUZZY_MIN:
                hits.append(SearchHit(product, round(min(best, 94.0), 1), "fuzzy"))
    # Best score first, then shorter names (closer to what was typed), then alphabetical.
    hits.sort(key=lambda h: (-h.score, len(h.product.name), h.product.name))
    return hits[:limit]
