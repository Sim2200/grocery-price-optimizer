import pytest

from grocery_optimizer.catalog import Product, load_catalog
from grocery_optimizer.matching import ProductMatcher, clean_name, normalize_alias_key


@pytest.fixture(scope="module")
def matcher():
    return ProductMatcher(load_catalog())


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("TJ ORG BANANAS", "banana (organic)"),
        ("Bananas, organic", "banana (organic)"),
        ("BANANAS", "banana"),
        ("GNT WHL MLK 1 GAL", "milk (whole)"),
        ("Milk 2% reduced fat 1 gal", "milk (2%)"),
        ("BNLS SKNLS CHKN BRST", "chicken breast (boneless)"),
        ("LG EGGS 12CT", "eggs (large)"),
        ("SIMPLY NATURE ORG BBY SPIN 5OZ", "baby spinach (organic)"),
        ("EVOO 16.9 FL OZ", "olive oil (extra virgin)"),
        ("GRND BF 85/15", "ground beef (85/15)"),
        ("ALMD MLK UNSWT", "almond milk (unsweetened)"),
    ],
)
def test_fuzzy_matches(matcher, raw, expected):
    result = matcher.match(raw)
    assert result.product == expected
    assert result.method == "fuzzy"
    assert not result.needs_review


def test_organic_and_conventional_are_kept_apart(matcher):
    assert matcher.match("ORG BANANAS").product == "banana (organic)"
    assert matcher.match("BANANAS").product == "banana"


def test_unknown_item_needs_review(matcher):
    result = matcher.match("KITCHEN SPONGE 3PK")
    assert result.product is None
    assert result.method == "unmatched"
    assert result.needs_review
    assert result.candidates  # still offers suggestions


def test_alias_wins_over_fuzzy():
    m = ProductMatcher(load_catalog(), aliases={"MYSTERY ITEM 42": "rolled oats"})
    result = m.match("mystery item 42")
    assert result.product == "rolled oats"
    assert result.method == "alias"


def test_add_alias_is_used_next_time():
    m = ProductMatcher(load_catalog())
    assert m.match("KITCHEN SPONGE").product is None
    m.add_alias("KITCHEN SPONGE", "tortilla chips")  # silly, but user is always right
    assert m.match("kitchen  sponge").product == "tortilla chips"


def test_llm_fallback_is_called_only_below_threshold():
    calls = []

    def fake_llm(raw, candidates):
        calls.append((raw, candidates))
        return "hummus (classic)"

    m = ProductMatcher(load_catalog(), llm_fallback=fake_llm)
    assert m.match("TJ ORG BANANAS").method == "fuzzy"
    assert calls == []
    result = m.match("CHICKPEA DIP MEDITERRANEAN")
    assert result.product == "hummus (classic)"
    assert result.method == "llm"
    assert result.needs_review
    assert len(calls) == 1


def test_llm_fallback_answer_outside_catalog_is_ignored():
    m = ProductMatcher(load_catalog(), llm_fallback=lambda raw, c: "unicorn steak")
    assert m.match("KITCHEN SPONGE").product is None


def test_clean_name_and_alias_key():
    assert clean_name("TJ ORG BANANAS 3 LB") == "organic bananas"
    assert normalize_alias_key("  Bananas,  ORGANIC ") == "bananas organic"


def test_product_rejects_bad_unit():
    with pytest.raises(ValueError):
        Product("x", "furlong")
