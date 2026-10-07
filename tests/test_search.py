"""Typeahead search: prefix first, typo-tolerant fuzzy second, limit respected."""

import pytest
from fastapi.testclient import TestClient

from grocery_optimizer.api import create_app
from grocery_optimizer.catalog import load_catalog
from grocery_optimizer.extraction import DemoReceiptExtractor
from grocery_optimizer.search import search_products

CATALOG = load_catalog()


def names(query, limit=8):
    return [h.product.name for h in search_products(CATALOG, query, limit)]


def test_prefix_matches_rank_first():
    hits = search_products(CATALOG, "ban")
    assert hits and all(h.match == "prefix" for h in hits[:1])
    assert any("banana" in h.product.name for h in hits)


def test_typo_still_finds_product():
    assert any("banana" in n for n in names("bananna"))


def test_empty_and_nonsense_queries_return_nothing():
    assert names("") == [] and names("   ") == []
    assert names("zzqxj") == []


def test_limit_is_respected():
    assert len(names("o", limit=3)) <= 3


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "t.db", extractor=DemoReceiptExtractor())) as c:
        yield c


def test_search_endpoint(client):
    body = client.get("/api/products/search", params={"q": "mil", "limit": 5}).json()
    assert 0 < len(body) <= 5
    assert {"name", "unit", "category", "score", "match"} <= body[0].keys()
    assert body[0]["match"] == "prefix" and "milk" in body[0]["name"]
    assert client.get("/api/products/search", params={"q": "x", "limit": 0}).status_code == 422
