"""Extraction tests with a mocked the LLM client (no network, no API key)."""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from grocery_optimizer.extraction import (
    FALLBACK_BETA,
    VisionReceiptExtractor,
    DemoReceiptExtractor,
    ExtractionError,
    media_type_for,
    parse_receipt_json,
)
from grocery_optimizer.llm_matching import LLMMatchFallback
from grocery_optimizer.schemas import RECEIPT_JSON_SCHEMA, LineItem, Receipt, consistency_warnings

GOOD_OUTPUT = {
    "store": "Trader Joe's",
    "date": "2026-07-11",
    "line_items": [
        {"raw_name": "TJ ORG BANANAS", "quantity": 2.1, "unit": "lb", "size": None,
         "unit_price": 0.79, "line_total": 1.66},
        {"raw_name": "WHL MILK 1 GAL", "quantity": 1, "unit": "each", "size": "1 gal",
         "unit_price": 3.49, "line_total": 3.49},
    ],
    "total": 5.15,
}


class FakeMessages:
    """Records the request and returns a canned response, like client.beta.messages."""

    def __init__(self, text=None, stop_reason="end_turn", error=None):
        self.text, self.stop_reason, self.error = text, stop_reason, error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        content = [] if self.text is None else [SimpleNamespace(type="text", text=self.text)]
        return SimpleNamespace(stop_reason=self.stop_reason, content=content)


def fake_client(**kwargs):
    messages = FakeMessages(**kwargs)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_extract_valid_response():
    client, messages = fake_client(text=json.dumps(GOOD_OUTPUT))
    receipt = VisionReceiptExtractor(client=client).extract(b"\x89PNG fake", "r.png")
    assert isinstance(receipt, Receipt)
    assert receipt.store == "Trader Joe's"
    assert receipt.line_items[0].unit == "lb"
    assert receipt.date.isoformat() == "2026-07-11"
    assert len(messages.calls) == 1


def test_request_uses_structured_output_image_block_and_fallback():
    client, messages = fake_client(text=json.dumps(GOOD_OUTPUT))
    VisionReceiptExtractor(client=client).extract(b"img", "receipt.JPG")
    req = messages.calls[0]
    assert req["model"] == ""
    assert req["output_config"]["format"] == {"type": "json_schema", "schema": RECEIPT_JSON_SCHEMA}
    block = req["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/jpeg"
    assert req["betas"] == [FALLBACK_BETA] and req["fallbacks"] == "default"


def test_pdf_is_sent_as_document_block():
    request = VisionReceiptExtractor(client=object()).build_request(b"%PDF", "receipt.pdf")
    block = request["messages"][0]["content"][0]
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"


def test_invalid_model_output_raises():
    bad = dict(GOOD_OUTPUT, line_items=[dict(GOOD_OUTPUT["line_items"][0], quantity=-1)])
    client, _ = fake_client(text=json.dumps(bad))
    with pytest.raises(ExtractionError, match="validation"):
        VisionReceiptExtractor(client=client).extract(b"x", "r.png")


def test_non_json_output_raises():
    client, _ = fake_client(text="Sorry, here is the receipt: ...")
    with pytest.raises(ExtractionError, match="not valid JSON"):
        VisionReceiptExtractor(client=client).extract(b"x", "r.png")


def test_refusal_and_truncation_raise():
    client, _ = fake_client(text=None, stop_reason="refusal")
    with pytest.raises(ExtractionError, match="declined"):
        VisionReceiptExtractor(client=client).extract(b"x", "r.png")
    client, _ = fake_client(text="{", stop_reason="max_tokens")
    with pytest.raises(ExtractionError, match="cut off"):
        VisionReceiptExtractor(client=client).extract(b"x", "r.png")


def test_api_connection_error_is_wrapped():
    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    client, _ = fake_client(error=err)
    with pytest.raises(ExtractionError, match="reach"):
        VisionReceiptExtractor(client=client).extract(b"x", "r.png")


def test_unsupported_file_type():
    with pytest.raises(ExtractionError):
        media_type_for("receipt.docx")


def test_json_schema_matches_pydantic_models():
    """The hand-written schema sent to the LLM must list the same fields as the Pydantic models."""
    assert set(RECEIPT_JSON_SCHEMA["properties"]) == set(Receipt.model_fields)
    item_schema = RECEIPT_JSON_SCHEMA["properties"]["line_items"]["items"]
    assert set(item_schema["properties"]) == set(LineItem.model_fields)
    # Structured outputs require every property to be required + no extra keys.
    assert set(RECEIPT_JSON_SCHEMA["required"]) == set(RECEIPT_JSON_SCHEMA["properties"])
    assert set(item_schema["required"]) == set(item_schema["properties"])
    assert RECEIPT_JSON_SCHEMA["additionalProperties"] is False
    assert item_schema["additionalProperties"] is False


def test_null_optional_fields_are_accepted():
    receipt = parse_receipt_json(dict(GOOD_OUTPUT, date=None, total=None))
    assert receipt.date is None and receipt.total is None


def test_consistency_warnings():
    receipt = parse_receipt_json(GOOD_OUTPUT)
    assert consistency_warnings(receipt) == []
    off = parse_receipt_json(dict(GOOD_OUTPUT, total=9.99))
    assert any("sum to" in w for w in consistency_warnings(off))


def test_demo_extractor_reads_sidecar_json(tmp_path):
    (tmp_path / "SYNTHETIC_x.json").write_text(json.dumps(GOOD_OUTPUT))
    extractor = DemoReceiptExtractor(tmp_path)
    assert extractor.extract(b"", "SYNTHETIC_x.png").store == "Trader Joe's"
    with pytest.raises(ExtractionError, match="Demo mode"):
        extractor.extract(b"", "my_real_receipt.jpg")


def test_llm_match_fallback_constrains_answer_to_candidates():
    client, messages = fake_client(text=json.dumps({"product": "hummus (classic)"}))
    fallback = LLMMatchFallback(client=client)
    assert fallback("CHICKPEA DIP", ["hummus (classic)", "black beans (canned)"]) == "hummus (classic)"
    enum = messages.calls[0]["output_config"]["format"]["schema"]["properties"]["product"]["enum"]
    assert enum == ["hummus (classic)", "black beans (canned)", "NONE"]

    client, _ = fake_client(text=json.dumps({"product": "NONE"}))
    assert LLMMatchFallback(client=client)("SPONGE", ["hummus (classic)"]) is None
