"""Scoring extracted receipts against hand-written ground truth.

How it works
------------
1. Align predicted line items to gold line items within each receipt. Every
   (gold, pred) pair gets a name-similarity score; pairs are taken greedily,
   best first, if both sides are still free and the score is >= 60.
2. Item-level:  TP = aligned pairs.
                precision = TP / predicted items, recall = TP / gold items.
3. Field-level: for each field, a hit is an aligned pair whose field values
   agree (numbers within 1 cent, units exact, names/sizes after normalization).
                precision_f = hits_f / predicted items
                recall_f    = hits_f / gold items
   So a missed line hurts recall for every field and a hallucinated line hurts
   precision for every field.
4. Receipt-level: store, date and printed-total match rates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .matching import normalize_alias_key
from .schemas import LineItem, Receipt
from .units import parse_size

ITEM_FIELDS = ("raw_name", "quantity", "unit", "size", "unit_price", "line_total")
ALIGN_THRESHOLD = 60.0
MONEY_TOLERANCE = 0.011


def _num_equal(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= MONEY_TOLERANCE


def field_equal(name: str, gold: LineItem, pred: LineItem) -> bool:
    g, p = getattr(gold, name), getattr(pred, name)
    if name == "raw_name":
        return normalize_alias_key(g) == normalize_alias_key(p)
    if name == "size":
        if g is None or p is None:
            return g is None and p is None
        return parse_size(g) == parse_size(p) or normalize_alias_key(g) == normalize_alias_key(p)
    if name == "unit":
        return g == p
    return _num_equal(g, p)


def align_items(gold: list[LineItem], pred: list[LineItem]) -> list[tuple[int, int]]:
    """Greedy best-first alignment of gold to predicted items by name similarity."""
    scored = []
    for gi, g in enumerate(gold):
        for pi, p in enumerate(pred):
            score = fuzz.ratio(normalize_alias_key(g.raw_name), normalize_alias_key(p.raw_name))
            # Small bonus when the money agrees, to break ties between same-named lines.
            if _num_equal(g.line_total, p.line_total):
                score += 5
            scored.append((score, gi, pi))
    scored.sort(reverse=True)
    used_g, used_p, pairs = set(), set(), []
    for score, gi, pi in scored:
        if score < ALIGN_THRESHOLD or gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        pairs.append((gi, pi))
    return pairs


@dataclass
class PRF:
    hits: int = 0
    n_pred: int = 0
    n_gold: int = 0

    @property
    def precision(self) -> float:
        return self.hits / self.n_pred if self.n_pred else 0.0

    @property
    def recall(self) -> float:
        return self.hits / self.n_gold if self.n_gold else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class EvalReport:
    n_receipts: int = 0
    items: PRF = field(default_factory=PRF)
    fields: dict[str, PRF] = field(default_factory=lambda: {f: PRF() for f in ITEM_FIELDS})
    store_matches: int = 0
    date_matches: int = 0
    total_matches: int = 0
    missing_predictions: list[str] = field(default_factory=list)

    def rate(self, count: int) -> float:
        return count / self.n_receipts if self.n_receipts else 0.0

    def as_dict(self) -> dict:
        return {
            "n_receipts": self.n_receipts,
            "items": _prf_dict(self.items),
            "fields": {name: _prf_dict(prf) for name, prf in self.fields.items()},
            "store_match_rate": round(self.rate(self.store_matches), 4),
            "date_match_rate": round(self.rate(self.date_matches), 4),
            "total_match_rate": round(self.rate(self.total_matches), 4),
            "missing_predictions": self.missing_predictions,
        }


def _prf_dict(prf: PRF) -> dict:
    return {"precision": round(prf.precision, 4), "recall": round(prf.recall, 4),
            "f1": round(prf.f1, 4), "hits": prf.hits, "n_pred": prf.n_pred, "n_gold": prf.n_gold}


def score_receipt(gold: Receipt, pred: Receipt, report: EvalReport) -> None:
    """Add one (gold, prediction) pair to a running report."""
    report.n_receipts += 1
    pairs = align_items(gold.line_items, pred.line_items)
    report.items.hits += len(pairs)
    report.items.n_pred += len(pred.line_items)
    report.items.n_gold += len(gold.line_items)
    for name, prf in report.fields.items():
        prf.n_pred += len(pred.line_items)
        prf.n_gold += len(gold.line_items)
        prf.hits += sum(field_equal(name, gold.line_items[g], pred.line_items[p]) for g, p in pairs)
    report.store_matches += normalize_alias_key(gold.store) == normalize_alias_key(pred.store)
    report.date_matches += gold.date == pred.date
    report.total_matches += _num_equal(gold.total, pred.total)


def evaluate(gold: dict[str, Receipt], predictions: dict[str, Receipt]) -> EvalReport:
    """Score every gold receipt. A gold receipt with no prediction counts as all-missed."""
    report = EvalReport()
    for key in sorted(gold):
        if key in predictions:
            score_receipt(gold[key], predictions[key], report)
        else:
            report.missing_predictions.append(key)
            report.n_receipts += 1
            report.items.n_gold += len(gold[key].line_items)
            for prf in report.fields.values():
                prf.n_gold += len(gold[key].line_items)
    return report
