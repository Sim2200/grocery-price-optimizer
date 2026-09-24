"""Optional LLM fallback for product matching.

Only called for receipt names that the rules + fuzzy matcher could not map
confidently. The LLM picks one of the top fuzzy candidates or "NONE"; the
JSON-schema `enum` makes it impossible to answer with a product that is not
in the catalog. Results are still flagged for human review.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from .config import LLM_MODEL
from .extraction import FALLBACK_BETA

NONE_CHOICE = "NONE"

PROMPT = """A grocery receipt line reads: "{raw_name}"

Which canonical product is it? Receipt names are often abbreviated
(ORG = organic, BNLS = boneless, WHL = whole) and may include store brands.
Pay attention to variants such as organic vs conventional and whole vs 2% milk.
If none of the options is the same product, answer {none}.

Options:
{options}"""


class LLMMatchFallback:
    def __init__(self, client: Any | None = None, model: str = LLM_MODEL) -> None:
        self._client = client
        self.model = model

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def __call__(self, raw_name: str, candidates: list[str]) -> str | None:
        if not candidates or not self.model:
            return None
        choices = [*candidates, NONE_CHOICE]
        schema = {
            "type": "object",
            "properties": {"product": {"type": "string", "enum": choices}},
            "required": ["product"],
            "additionalProperties": False,
        }
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=4096,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                messages=[{"role": "user", "content": PROMPT.format(
                    raw_name=raw_name, none=NONE_CHOICE,
                    options="\n".join(f"- {c}" for c in candidates))}],
                # A short classification: low effort keeps it fast and cheap.
                output_config={"effort": "low",
                               "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIError:
            return None  # the fallback is best-effort; the item goes to review instead
        if response.stop_reason != "end_turn":
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            return None
        choice = json.loads(text).get("product")
        return None if choice in (None, NONE_CHOICE) else choice
