"""Eval-harness tests on a tiny hand-checkable example."""

import pytest

from grocery_optimizer.evaluation import align_items, evaluate
from grocery_optimizer.schemas import LineItem, Receipt


def item(name, qty=1, unit="each", size=None, price=1.0, total=None):
    return LineItem(raw_name=name, quantity=qty, unit=unit, size=size, unit_price=price,
                    line_total=price * qty if total is None else total)


GOLD = Receipt(store="Aldi", date="2026-07-01", total=6.0, line_items=[
    item("ORG BANANAS", 2, "lb", price=0.5),          # 1.00
    item("WHL MILK 1 GAL", size="1 gal", price=3.0),  # 3.00
    item("LG EGGS 12CT", size="12 ct", price=2.0),    # 2.00
])


def test_perfect_prediction():
    report = evaluate({"r": GOLD}, {"r": GOLD})
    assert report.items.f1 == 1.0
    assert all(prf.f1 == 1.0 for prf in report.fields.values())
    assert report.rate(report.total_matches) == 1.0


def test_hand_checkable_errors():
    # Prediction: bananas right; milk price misread; eggs missed; a fake BAG FEE line.
    pred = Receipt(store="ALDI", date="2026-07-01", total=6.1, line_items=[
        item("ORG BANANAS", 2, "lb", price=0.5),
        item("WHL MILK 1 GAL", size="1 GAL", price=3.1, total=3.0),
        item("BAG FEE", price=0.1),
    ])
    report = evaluate({"r": GOLD}, {"r": pred})
    # 2 aligned pairs, 3 predicted items, 3 gold items.
    assert report.items.precision == pytest.approx(2 / 3)
    assert report.items.recall == pytest.approx(2 / 3)
    # unit_price correct only for bananas: 1 hit.
    assert report.fields["unit_price"].precision == pytest.approx(1 / 3)
    # size: bananas (None == None) and milk ("1 GAL" parses equal to "1 gal"): 2 hits.
    assert report.fields["size"].recall == pytest.approx(2 / 3)
    assert report.rate(report.store_matches) == 1.0  # case-insensitive
    assert report.rate(report.total_matches) == 0.0


def test_missing_prediction_counts_as_all_missed():
    report = evaluate({"a": GOLD, "b": GOLD}, {"a": GOLD})
    assert report.missing_predictions == ["b"]
    assert report.items.recall == pytest.approx(0.5)
    assert report.items.precision == 1.0


def test_alignment_handles_reordering_and_typos():
    pred = [GOLD.line_items[2], item("0RG BANANAS", 2, "lb", price=0.5), GOLD.line_items[1]]
    pairs = sorted(align_items(GOLD.line_items, pred))
    assert pairs == [(0, 1), (1, 2), (2, 0)]
