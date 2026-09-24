"""Recipe / free-text list assistant: offline parser and the LLM tool-use loop (mocked)."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from grocery_optimizer.api import create_app
from grocery_optimizer.catalog import load_catalog
from grocery_optimizer.extraction import DemoReceiptExtractor
from grocery_optimizer.list_assistant import (
    MAX_TOOL_ROUNDS,
    DemoListAssistant,
    ListAssistantError,
    LLMListAssistant,
)
from grocery_optimizer.matching import ProductMatcher

CATALOG = load_catalog()
MATCHER = ProductMatcher(CATALOG)


def _by_request(draft):
    return {line.request: line for line in draft.lines}


# ----- offline assistant ------------------------------------------------------------
def test_demo_recipe_scales_with_servings():
    two = DemoListAssistant(CATALOG, MATCHER).build("tacos for 2").lines
    four = DemoListAssistant(CATALOG, MATCHER).build("Tacos for 4").lines
    beef2 = next(line for line in two if line.product == "ground beef (85/15)")
    beef4 = next(line for line in four if line.product == "ground beef (85/15)")
    assert (beef2.quantity, beef4.quantity, beef4.unit) == (0.5, 1.0, "lb")


def test_demo_free_text_quantities_and_units():
    draft = DemoListAssistant(CATALOG, MATCHER).build(
        "2 lb chicken breast, a dozen eggs\n3 avocados; 1 gal whole milk, 8 oz cheddar")
    lines = _by_request(draft)
    assert draft.source == "demo"
    assert (lines["2 lb chicken breast"].product, lines["2 lb chicken breast"].quantity) == (
        "chicken breast (boneless)", 2.0)
    assert (lines["a dozen eggs"].product, lines["a dozen eggs"].quantity) == ("eggs (large)", 12.0)
    assert lines["3 avocados"].quantity == 3.0 and lines["3 avocados"].unit == "each"
    assert lines["1 gal whole milk"].product == "milk (whole)"
    assert lines["8 oz cheddar"].product == "cheddar cheese"


def test_demo_converts_units_and_flags_unknowns():
    lines = _by_request(DemoListAssistant(CATALOG, MATCHER).build("16 oz ground beef, unicorn steaks"))
    assert lines["16 oz ground beef"].quantity == pytest.approx(1.0)  # 16 oz -> 1 lb
    assert lines["unicorn steaks"].product is None and "no matching" in lines["unicorn steaks"].note


# ----- LLM assistant with a fake client ---------------------------------------------
class FakeMessages:
    """Replays scripted responses and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        # Copy the message list: the assistant keeps appending to the same list object.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def _tool_use(*queries):
    blocks = [SimpleNamespace(type="text", text="Let me look those up.")]
    blocks += [SimpleNamespace(type="tool_use", id=f"tu_{i}", name="search_catalog",
                               input={"query": q}) for i, q in enumerate(queries)]
    return SimpleNamespace(stop_reason="tool_use", content=blocks)


def _answer(items):
    return SimpleNamespace(stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text=json.dumps({"items": items}))])


def _assistant(responses):
    messages = FakeMessages(responses)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return LLMListAssistant(CATALOG, MATCHER, client=client, model="test-model"), messages


def test_llm_tool_loop_searches_catalog_then_answers():
    assistant, fake = _assistant([
        _tool_use("ground beef", "salt"),
        _answer([
            {"request": "1 lb ground beef", "product": "ground beef (85/15)", "quantity": 1,
             "note": ""},
            {"request": "salt", "product": "NONE", "quantity": 0, "note": "not in catalog"},
        ]),
    ])
    draft = assistant.build("tacos for 4")
    assert draft.source == "llm"
    beef, salt = draft.lines
    assert (beef.product, beef.quantity, beef.unit) == ("ground beef (85/15)", 1.0, "lb")
    assert salt.product is None and salt.quantity == 0

    first, second = fake.requests
    assert first["model"] == "test-model" and first["tools"][0]["name"] == "search_catalog"
    # The answer schema only allows catalog products (plus NONE).
    enum = first["output_config"]["format"]["schema"]["properties"]["items"]["items"][
        "properties"]["product"]["enum"]
    assert "ground beef (85/15)" in enum and "NONE" in enum and "unicorn" not in enum
    # Second request: the model's tool calls, then *all* results in one user message.
    assert second["messages"][1]["role"] == "assistant"
    results = second["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["tu_0", "tu_1"]
    beef_hits = json.loads(results[0]["content"])
    assert beef_hits[0]["name"] == "ground beef (85/15)" and beef_hits[0]["unit"] == "lb"


def test_llm_errors_become_friendly_messages():
    refusal = SimpleNamespace(stop_reason="refusal", content=[])
    with pytest.raises(ListAssistantError, match="declined"):
        _assistant([refusal])[0].build("x")
    with pytest.raises(ListAssistantError, match="Too many"):
        _assistant([_tool_use("milk")] * MAX_TOOL_ROUNDS)[0].build("x")
    with pytest.raises(ListAssistantError, match="GROCERY_LLM_MODEL"):
        LLMListAssistant(CATALOG, MATCHER, client=object(), model="").build("x")


# ----- API ----------------------------------------------------------------------------
def test_assist_endpoint_offline(tmp_path):
    app = create_app(db_path=tmp_path / "t.db", extractor=DemoReceiptExtractor(),
                     list_assistant=DemoListAssistant)
    with TestClient(app) as c:
        body = c.post("/api/shopping-list/assist", json={"text": "spaghetti for 2"}).json()
        assert body["source"] == "demo" and body["notes"]
        assert {line["product"] for line in body["lines"]} >= {"pasta (spaghetti)", "roma tomato"}
        assert c.post("/api/shopping-list/assist", json={"text": ""}).status_code == 422


def test_assist_endpoint_with_mocked_llm(tmp_path):
    fake_assistant, _ = _assistant([_answer([
        {"request": "eggs", "product": "eggs (large)", "quantity": 12, "note": ""}])])
    app = create_app(db_path=tmp_path / "t.db", extractor=DemoReceiptExtractor(),
                     list_assistant=lambda catalog, matcher: fake_assistant)
    with TestClient(app) as c:
        body = c.post("/api/shopping-list/assist", json={"text": "a dozen eggs"}).json()
        assert body["source"] == "llm"
        assert body["lines"] == [{"request": "eggs", "product": "eggs (large)", "quantity": 12.0,
                                  "unit": "each", "note": ""}]

    failing, _ = _assistant([SimpleNamespace(stop_reason="refusal", content=[])])
    app = create_app(db_path=tmp_path / "t2.db", extractor=DemoReceiptExtractor(),
                     list_assistant=lambda catalog, matcher: failing)
    with TestClient(app) as c:
        r = c.post("/api/shopping-list/assist", json={"text": "x"})
        assert r.status_code == 422 and "declined" in r.json()["detail"]
