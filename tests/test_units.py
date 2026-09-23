import pytest

from grocery_optimizer.schemas import LineItem
from grocery_optimizer.units import (
    Quantity,
    comparable_unit_price,
    conversion_factor,
    normalize_unit,
    parse_size,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("16 oz", Quantity(16, "oz")),
        ("16oz", Quantity(16, "oz")),
        ("1 gal", Quantity(1, "gal")),
        ("1/2 gal", Quantity(0.5, "gal")),
        ("52 FL OZ", Quantity(52, "fl_oz")),
        ("16.9 fl. oz", Quantity(16.9, "fl_oz")),
        ("12 ct", Quantity(12, "each")),
        ("2 x 8oz", Quantity(16, "oz")),
        ("1.5 lb", Quantity(1.5, "lb")),
        ("500ml", Quantity(500, "ml")),
        ("1 dozen", Quantity(1, "dozen")),
        ("EGGS LARGE DOZEN", Quantity(1, "dozen")),
        ("WHOLE MILK 1 GAL", Quantity(1, "gal")),
    ],
)
def test_parse_size(text, expected):
    assert parse_size(text) == expected


@pytest.mark.parametrize("text", [None, "", "BANANAS", "ORG BBY SPINACH"])
def test_parse_size_none(text):
    assert parse_size(text) is None


def test_normalize_unit():
    assert normalize_unit("LBS") == "lb"
    assert normalize_unit("fl. oz") == "fl_oz"
    assert normalize_unit("ct") == "each"
    assert normalize_unit("parsecs") is None


def test_conversion_factor():
    assert conversion_factor("lb", "oz") == 16
    assert conversion_factor("gal", "fl_oz") == 128
    assert conversion_factor("oz", "lb") == pytest.approx(1 / 16)
    with pytest.raises(ValueError):
        conversion_factor("lb", "gal")


def _item(**kw):
    base = dict(raw_name="X", quantity=1, unit="each", size=None, unit_price=1.0, line_total=1.0)
    base.update(kw)
    return LineItem(**base)


def test_sold_by_weight():
    # $0.69/lb bananas compared per lb and per oz
    item = _item(unit="lb", quantity=2.5, unit_price=0.69, line_total=1.73)
    assert comparable_unit_price(item, "lb") == pytest.approx(0.69)
    assert comparable_unit_price(item, "oz") == pytest.approx(0.69 / 16)


def test_sold_by_kg_to_lb():
    item = _item(unit="kg", unit_price=2.20)
    assert comparable_unit_price(item, "lb") == pytest.approx(2.20 / 2.20462, rel=1e-3)


def test_package_with_size():
    # 1.5 lb pack of chicken for $6.00 -> $4.00/lb
    item = _item(size="1.5 lb", unit_price=6.00)
    assert comparable_unit_price(item, "lb") == pytest.approx(4.00)
    # 32 oz yogurt for $4.80 -> $0.15/oz
    assert comparable_unit_price(_item(size="32 oz", unit_price=4.80), "oz") == pytest.approx(0.15)
    # half gallon almond milk $2.00 -> $4.00/gal
    assert comparable_unit_price(_item(size="64 fl oz", unit_price=2.0), "gal") == pytest.approx(4.0)


def test_eggs_per_each():
    assert comparable_unit_price(_item(size="12 ct", unit_price=3.00), "each") == pytest.approx(0.25)
    assert comparable_unit_price(_item(size="1 dozen", unit_price=3.60), "each") == pytest.approx(0.30)


def test_size_found_in_raw_name():
    item = _item(raw_name="WHOLE MILK 1 GAL", unit_price=3.49)
    assert comparable_unit_price(item, "gal") == pytest.approx(3.49)


def test_not_comparable():
    # A loose package with no size can't be priced per lb.
    assert comparable_unit_price(_item(unit_price=2.0), "lb") is None
    # Weight-priced item can't become a volume price.
    assert comparable_unit_price(_item(unit="lb", unit_price=2.0), "gal") is None
    # But a per-each price with no size is fine for an 'each' product.
    assert comparable_unit_price(_item(unit_price=1.25), "each") == pytest.approx(1.25)
