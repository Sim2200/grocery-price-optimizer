"""Product-matching eval, with an ablation that turns the rules step off.

Two label sets:
  1. data/synthetic/SYNTHETIC_match_labels.json - every raw name in the synthetic
     receipts. The generator and the abbreviation rules were written together,
     so this set is optimistic by construction.
  2. evals/data/matching_handwritten.json - hand-written receipt-style strings
     written separately from the generator (still not real receipts), including
     non-grocery lines that should NOT be auto-matched.

For each set we report, using only the catalog (no alias table, no LLM):
  auto-accepted correct / auto-accepted wrong / sent to review,
  for the full pipeline and for fuzzy matching without the rules step.

Run: python evals/matching_eval.py
"""

from __future__ import annotations

import json
from pathlib import Path

from grocery_optimizer.catalog import load_catalog
from grocery_optimizer.matching import ProductMatcher

ROOT = Path(__file__).resolve().parent.parent
LABEL_SETS = {
    "synthetic receipts (optimistic)": ROOT / "data" / "synthetic" / "SYNTHETIC_match_labels.json",
    "hand-written strings": ROOT / "evals" / "data" / "matching_handwritten.json",
}


def load_labels(path: Path) -> dict[str, str | None]:
    data = json.loads(path.read_text())
    return data["labels"] if "labels" in data else data


def score(matcher: ProductMatcher, labels: dict[str, str | None]) -> dict[str, int]:
    counts = {"n": len(labels), "correct": 0, "wrong": 0, "review": 0}
    for raw, expected in labels.items():
        result = matcher.match(raw)
        if result.needs_review:
            counts["review"] += 1  # a human will look at it; not an error
            if expected is None:
                counts["correct"] += 1  # correctly refused to auto-match
                counts["review"] -= 1
        elif result.product == expected:
            counts["correct"] += 1
        else:
            counts["wrong"] += 1
    return counts


def main() -> None:
    catalog = load_catalog()
    variants = {
        "rules + fuzzy": ProductMatcher(catalog),
        "fuzzy only (no rules)": ProductMatcher(catalog, use_rules=False),
    }
    print(f"{'label set':<34}{'matcher':<24}{'n':>4}{'correct':>9}{'wrong':>7}{'review':>8}")
    for set_name, path in LABEL_SETS.items():
        labels = load_labels(path)
        for name, matcher in variants.items():
            c = score(matcher, labels)
            print(f"{set_name:<34}{name:<24}{c['n']:>4}{c['correct']:>9}{c['wrong']:>7}{c['review']:>8}")
    print("\ncorrect = auto-matched to the right product, or correctly NOT auto-matched (null label)")
    print("wrong   = auto-matched to the wrong product (the costly error)")
    print("review  = sent to the human review queue")


if __name__ == "__main__":
    main()
