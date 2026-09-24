"""Receipt extraction: image / PDF -> validated `Receipt`.

Two extractors share one interface, `extract(file_bytes, filename) -> Receipt`:

- VisionReceiptExtractor: sends the image or PDF to the LLM with a JSON
  schema (structured outputs), so the reply is guaranteed to be JSON in the
  right shape. We still validate it with Pydantic, which also enforces rules
  a JSON schema can't express nicely (quantity > 0, real calendar dates).
- DemoReceiptExtractor: offline stand-in used when there is no API key. It
  only "extracts" the bundled synthetic receipts by returning their
  ground-truth JSON, so the rest of the app can be demoed end to end.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Protocol

import anthropic
from pydantic import ValidationError

from .config import LLM_MODEL, SYNTHETIC_RECEIPTS_DIR, demo_mode
from .schemas import RECEIPT_JSON_SCHEMA, Receipt

SYSTEM_PROMPT = """You read photos and PDFs of grocery store receipts and return their contents as JSON.

How to fill each field:
- store: the store or chain name as printed (e.g. "Trader Joe's", "ALDI", "Giant").
- date: purchase date as YYYY-MM-DD, or null if not printed.
- line_items: one entry per purchased product, in receipt order. Skip subtotal, tax,
  bag fees, payment, change and loyalty-summary lines.
  - raw_name: the item text exactly as printed, keeping abbreviations (e.g. "TJ ORG BANANAS").
  - Sold by weight (e.g. "2.13 lb @ 0.69 /lb"): quantity = the weight, unit = that weight
    unit, unit_price = price per weight unit.
  - Sold per package or piece: quantity = number of packages, unit = "each",
    unit_price = price of one package.
  - size: package size if printed anywhere on the line or in the name (e.g. "16 oz",
    "1 gal", "12 ct"), otherwise null.
  - line_total: amount charged for the line. If an item-specific discount is printed
    directly under the item, subtract it.
- total: the grand total the customer paid, or null if not visible.

Only report what is printed. Use null instead of guessing a missing value."""

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}

# Server-side refusal fallback: if the primary model declines, the API
# retries on Anthropic's recommended fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ExtractionError(RuntimeError):
    """Raised when a receipt could not be turned into a valid `Receipt`."""


class ReceiptExtractor(Protocol):
    def extract(self, file_bytes: bytes, filename: str) -> Receipt: ...


def media_type_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in MEDIA_TYPES:
        raise ExtractionError(f"Unsupported file type '{suffix}'. Use PNG, JPEG, WEBP, GIF or PDF.")
    return MEDIA_TYPES[suffix]


def parse_receipt_json(data: str | dict[str, Any]) -> Receipt:
    """Validate raw model output (JSON text or dict) into a `Receipt`."""
    try:
        payload = json.loads(data) if isinstance(data, str) else data
        return Receipt.model_validate(payload)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Model output was not valid JSON: {exc}") from exc
    except ValidationError as exc:
        raise ExtractionError(f"Model output failed validation:\n{exc}") from exc


class VisionReceiptExtractor:
    """Extract a receipt with an LLM vision model and structured outputs."""

    def __init__(self, client: Any | None = None, model: str = LLM_MODEL,
                 use_fallbacks: bool = True) -> None:
        # The client is injectable so tests can pass a fake one.
        # anthropic.Anthropic() reads ANTHROPIC_API_KEY from the environment.
        self._client = client
        self.model = model
        self.use_fallbacks = use_fallbacks

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def build_request(self, file_bytes: bytes, filename: str) -> dict[str, Any]:
        """Keyword arguments for `client.beta.messages.create` (kept separate for testing)."""
        media_type = media_type_for(filename)
        data = base64.standard_b64encode(file_bytes).decode("utf-8")
        block_type = "document" if media_type == "application/pdf" else "image"
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": block_type,
                     "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": "Extract this grocery receipt."},
                ],
            }],
            "output_config": {"format": {"type": "json_schema", "schema": RECEIPT_JSON_SCHEMA}},
        }
        if self.use_fallbacks:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    def extract(self, file_bytes: bytes, filename: str) -> Receipt:
        if not self.model:
            raise ExtractionError("No model configured. Set GROCERY_LLM_MODEL to a vision-capable model ID.")
        request = self.build_request(file_bytes, filename)
        try:
            response = self.client.beta.messages.create(**request)
        except anthropic.AuthenticationError as exc:
            raise ExtractionError("Anthropic API key was rejected. Check ANTHROPIC_API_KEY.") from exc
        except anthropic.RateLimitError as exc:
            raise ExtractionError("Rate limited by the Anthropic API. Try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise ExtractionError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionError("Could not reach the Anthropic API.") from exc

        if response.stop_reason == "refusal":
            raise ExtractionError("The model declined to process this file.")
        if response.stop_reason == "max_tokens":
            raise ExtractionError("Receipt output was cut off (max_tokens). Try a smaller file.")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise ExtractionError("Model returned no text output.")
        return parse_receipt_json(text)


class DemoReceiptExtractor:
    """Offline extractor for the bundled SYNTHETIC receipts.

    Upload one of the images in data/synthetic/images and it returns the
    matching ground-truth JSON. Anything else raises a helpful error.
    """

    def __init__(self, receipts_dir: Path = SYNTHETIC_RECEIPTS_DIR) -> None:
        self.receipts_dir = Path(receipts_dir)

    def extract(self, file_bytes: bytes, filename: str) -> Receipt:
        sidecar = self.receipts_dir / f"{Path(filename).stem}.json"
        if not sidecar.exists():
            raise ExtractionError(
                "Demo mode (no ANTHROPIC_API_KEY) can only read the bundled synthetic receipt "
                "images. Set ANTHROPIC_API_KEY for real extraction, or use manual / CSV entry."
            )
        return parse_receipt_json(sidecar.read_text())


def get_extractor() -> ReceiptExtractor:
    """The LLM extractor when an API key is configured, otherwise the offline demo extractor."""
    return DemoReceiptExtractor() if demo_mode() else VisionReceiptExtractor()
