"""Extraction eval: field-level precision / recall / F1 against ground truth.

Two ways to get predictions:

  # 1) Score predictions that already exist as JSON files (same file stem as the gold file).
  python evals/extraction_eval.py --gold data/synthetic/receipts \
      --pred evals/data/synthetic_noisy_predictions

  # 2) Run an extractor on images now, save its outputs, then score them.
  #    --extractor llm needs ANTHROPIC_API_KEY and costs API credits.
  python evals/extraction_eval.py --gold data/synthetic/receipts \
      --images data/synthetic/images --extractor llm

The bundled example (option 1) scores SYNTHETIC predictions with errors injected
by scripts/generate_synthetic_data.py. Its numbers only show that the harness
works; they say nothing about how well the LLM reads real receipts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from grocery_optimizer.evaluation import ITEM_FIELDS, EvalReport, evaluate
from grocery_optimizer.extraction import (
    VisionReceiptExtractor,
    DemoReceiptExtractor,
    ExtractionError,
    MEDIA_TYPES,
    parse_receipt_json,
)
from grocery_optimizer.schemas import Receipt

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def load_dir(directory: Path) -> dict[str, Receipt]:
    return {p.stem: parse_receipt_json(p.read_text()) for p in sorted(directory.glob("*.json"))}


def run_extractor(images: Path, extractor_name: str, out_dir: Path) -> dict[str, Receipt]:
    extractor = VisionReceiptExtractor() if extractor_name == "llm" else DemoReceiptExtractor()
    out_dir.mkdir(parents=True, exist_ok=True)
    predictions: dict[str, Receipt] = {}
    for path in sorted(p for p in images.iterdir() if p.suffix.lower() in MEDIA_TYPES):
        try:
            receipt = extractor.extract(path.read_bytes(), path.name)
        except ExtractionError as exc:
            print(f"  {path.name}: FAILED ({exc})")
            continue
        predictions[path.stem] = receipt
        (out_dir / f"{path.stem}.json").write_text(receipt.model_dump_json(indent=2))
        print(f"  {path.name}: {len(receipt.line_items)} items")
    return predictions


def print_report(report: EvalReport, label: str) -> None:
    print(f"\n{label}")
    print(f"receipts scored: {report.n_receipts}")
    print(f"\n{'':<12}{'precision':>10}{'recall':>10}{'F1':>10}")
    print(f"{'line items':<12}{report.items.precision:>10.3f}{report.items.recall:>10.3f}{report.items.f1:>10.3f}")
    for name in ITEM_FIELDS:
        prf = report.fields[name]
        print(f"{name:<12}{prf.precision:>10.3f}{prf.recall:>10.3f}{prf.f1:>10.3f}")
    print(f"\nstore match rate: {report.rate(report.store_matches):.3f}")
    print(f"date match rate:  {report.rate(report.date_matches):.3f}")
    print(f"total match rate: {report.rate(report.total_matches):.3f}")
    if report.missing_predictions:
        print(f"no prediction for: {', '.join(report.missing_predictions)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gold", type=Path, required=True, help="dir of ground-truth receipt JSON")
    parser.add_argument("--pred", type=Path, help="dir of predicted receipt JSON")
    parser.add_argument("--images", type=Path, help="dir of receipt images/PDFs to extract now")
    parser.add_argument("--extractor", choices=["llm", "demo"], default="llm")
    parser.add_argument("--json", type=Path, help="also write the metrics as JSON here")
    args = parser.parse_args()

    gold = load_dir(args.gold)
    if args.pred:
        predictions, label = load_dir(args.pred), f"Predictions from {args.pred}"
    elif args.images:
        run_dir = RESULTS_DIR / f"{args.extractor}_{dt.datetime.now():%Y%m%d_%H%M%S}"
        print(f"Extracting {args.images} with the {args.extractor} extractor -> {run_dir}")
        predictions, label = run_extractor(args.images, args.extractor, run_dir), f"{args.extractor} extractor"
    else:
        parser.error("pass --pred or --images")

    if any("synthetic" in str(p).lower() for p in (args.gold, args.pred, args.images) if p):
        label += "  [SYNTHETIC data - not a real-world accuracy number]"
    report = evaluate(gold, predictions)
    print_report(report, label)
    if args.json:
        args.json.write_text(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    main()
