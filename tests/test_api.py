"""REST API tests using FastAPI's TestClient (no network, no API key)."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from grocery_optimizer.api import create_app
from grocery_optimizer.config import SYNTHETIC_IMAGES_DIR
from grocery_optimizer.extraction import VisionReceiptExtractor, DemoReceiptExtractor


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "test.db", extractor=DemoReceiptExtractor())
    with TestClient(app) as c:
        yield c


@pytest.fixture
def demo_client(client):
    assert client.post("/api/demo/load", json={"reset": True}).json()["receipts_loaded"] == 16
    return client


def test_health_reports_demo_mode(client):
    body = client.get("/api/health").json()
    assert body == {"status": "ok", "demo_mode": True, "extractor": "demo", "model": ""}


def test_openapi_docs_available(client):
    spec = client.get("/openapi.json").json()
    assert "/api/plan" in spec["paths"] and "/api/receipts/extract" in spec["paths"]


def test_products_and_custom_product(client):
    names = [p["name"] for p in client.get("/api/products").json()]
    assert "banana (organic)" in names
    r = client.post("/api/products", json={"name": "kimchi", "unit": "oz", "category": "deli"})
    assert r.status_code == 201
    assert client.post("/api/products", json={"name": "x", "unit": "furlong"}).status_code == 422


def test_upload_extract_review_save_flow(client):
    image = next(SYNTHETIC_IMAGES_DIR.glob("SYNTHETIC_aldi_*.png"))
    r = client.post("/api/receipts/extract", files={"file": (image.name, image.read_bytes(), "image/png")})
    assert r.status_code == 200
    draft = r.json()
    assert draft["store"] == "Aldi" and draft["source"] == "demo"
    assert all(line["product"] for line in draft["lines"])  # synthetic names all match
    # Nothing saved until the user confirms.
    assert client.get("/api/receipts").json() == []

    # User corrects the first line and saves.
    draft["lines"][0]["product"] = "rolled oats"
    draft["lines"][0]["match_method"] = "user"
    r = client.post("/api/receipts", json={k: draft[k] for k in
                                           ("store", "date", "total", "lines", "source", "file_name")})
    assert r.status_code == 201
    receipt_id = r.json()["receipt_id"]
    items = client.get(f"/api/receipts/{receipt_id}/items").json()
    assert items and any(i["product"] == "rolled oats" for i in items)
    raw = draft["lines"][0]["item"]["raw_name"]
    aliases = {a["product"] for a in client.get("/api/aliases").json()}
    assert "rolled oats" in aliases, raw


def test_extract_unknown_file_in_demo_mode_is_422(client):
    r = client.post("/api/receipts/extract", files={"file": ("mine.jpg", b"not really", "image/jpeg")})
    assert r.status_code == 422
    assert "Demo mode" in r.json()["detail"]


def test_extract_with_mocked_llm(tmp_path):
    """Full upload path through the LLM extractor with a fake Anthropic client."""
    output = {"store": "LIDL #88", "date": "2026-08-01", "total": 2.37, "line_items": [
        {"raw_name": "Bananas, organic", "quantity": 3.0, "unit": "lb", "size": None,
         "unit_price": 0.79, "line_total": 2.37}]}
    fake_messages = SimpleNamespace(create=lambda **kw: SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(output))]))
    fake_client = SimpleNamespace(beta=SimpleNamespace(messages=fake_messages))
    app = create_app(db_path=tmp_path / "t.db", extractor=VisionReceiptExtractor(client=fake_client, model="test-model"))
    with TestClient(app) as c:
        assert c.get("/api/health").json()["extractor"] == "llm"
        draft = c.post("/api/receipts/extract", files={"file": ("r.png", b"png", "image/png")}).json()
        assert draft["source"] == "llm"
        assert draft["lines"][0]["product"] == "banana (organic)"
        c.post("/api/receipts", json={k: draft[k] for k in ("store", "date", "total", "lines", "source")})
        assert c.get("/api/stores").json() == ["Lidl"]  # "LIDL #88" normalized


def test_csv_manual_entry(client):
    csv = ("store,date,raw_name,quantity,unit,size,unit_price,line_total,total\n"
           "Aldi,2026-07-02,ORG BANANAS,2,lb,,0.79,1.58,\n"
           "Aldi,2026-07-02,MYSTERY SNACK,1,each,,2.00,2.00,\n")
    drafts = client.post("/api/receipts/parse-csv", json={"csv": csv}).json()
    assert len(drafts) == 1
    lines = drafts[0]["lines"]
    assert lines[0]["product"] == "banana (organic)"
    assert lines[1]["product"] is None and lines[1]["needs_review"]
    bad = client.post("/api/receipts/parse-csv", json={"csv": "store,raw_name\nA,b\n"})
    assert bad.status_code == 422


def test_save_rejects_unknown_product(client):
    body = {"store": "Aldi", "lines": [{"item": {"raw_name": "x", "quantity": 1, "unit": "each",
            "size": None, "unit_price": 1, "line_total": 1}, "product": "unicorn", "match_method": "user"}]}
    assert client.post("/api/receipts", json=body).status_code == 422


def test_price_table_and_history(demo_client):
    table = demo_client.get("/api/prices").json()
    assert table["stores"] == ["Aldi", "Giant", "Lidl", "Trader Joe's"]
    row = next(r for r in table["rows"] if r["product"] == "milk (whole)")
    cheapest = row["cheapest_store"]
    assert all(row["prices"][cheapest]["price"] <= cell["price"] for cell in row["prices"].values())
    history = demo_client.get("/api/prices/history", params={"product": "milk (whole)"}).json()
    assert history and {"store", "date", "unit_price"} <= set(history[0])
    assert demo_client.get("/api/prices", params={"method": "median"}).status_code == 422


def test_rematch_line_item(demo_client):
    item = demo_client.get("/api/line-items").json()[0]
    r = demo_client.patch(f"/api/line-items/{item['id']}", json={"product": "rolled oats", "remember": False})
    assert r.status_code == 200 and r.json()["product"] == "rolled oats"
    assert demo_client.patch("/api/line-items/999999", json={"product": None}).status_code == 404


def test_plan_endpoint(demo_client):
    items = demo_client.get("/api/demo/shopping-list").json()
    r = demo_client.post("/api/plan", json={"items": items, "trip_cost": 5})
    assert r.status_code == 200
    body = r.json()
    opt = body["optimal"]
    assert opt["status"] == "Optimal"
    assert opt["total"] == pytest.approx(opt["items_total"] + opt["trips_total"], abs=0.01)
    assert opt["total"] <= body["greedy"]["total"] + 1e-6
    if body["single_store"]:
        assert opt["total"] <= body["single_store"]["total"] + 1e-6
    # Every stop lists what to buy there.
    assert sum(len(s["items"]) for s in opt["stops"]) == len(items) - len(body["unavailable"])


def test_plan_respects_store_choice_and_max_stores(demo_client):
    items = [{"product": "milk (whole)", "quantity": 1}, {"product": "banana", "quantity": 2}]
    one = demo_client.post("/api/plan", json={"items": items, "max_stores": 1, "trip_cost": 0}).json()
    assert len(one["optimal"]["stops"]) == 1
    only = demo_client.post("/api/plan", json={"items": items, "stores": ["Giant"]}).json()
    assert {s["store"] for s in only["optimal"]["stops"]} <= {"Giant"}


def test_plan_validation(client):
    assert client.post("/api/plan", json={"items": []}).status_code == 422
    assert client.post("/api/plan", json={"items": [{"product": "x", "quantity": -1}]}).status_code == 422


def test_delete_receipt(demo_client):
    rid = demo_client.get("/api/receipts").json()[0]["id"]
    assert demo_client.delete(f"/api/receipts/{rid}").status_code == 204
    assert rid not in [r["id"] for r in demo_client.get("/api/receipts").json()]


def test_health_probes(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_readiness_fails_when_database_is_down(client, monkeypatch):
    from grocery_optimizer.db import PriceDB

    def broken(self):
        raise ConnectionError("db down")

    monkeypatch.setattr(PriceDB, "ping", broken)
    r = client.get("/readyz")
    assert r.status_code == 503 and "ConnectionError" in r.json()["detail"]
    assert client.get("/healthz").status_code == 200  # liveness is unaffected
