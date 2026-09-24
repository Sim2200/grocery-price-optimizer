"""Recipe / free-text list assistant: "tacos for 4" -> a structured shopping list.

Two assistants share one interface, `build(text) -> ListDraft`:

- LLMListAssistant: a small tool-use loop. The model gets one tool,
  `search_catalog(query)`, backed by the same ProductMatcher used for
  receipts, so it can look up which canonical products exist and their units.
  When it is done it answers in a JSON schema (structured outputs) whose
  `product` field is an enum of catalog names plus "NONE", so it cannot
  invent a product we have no prices for.
- DemoListAssistant: offline and deterministic (no API key). It knows a few
  recipes ("tacos for 4") and otherwise reads one item per line or comma
  ("2 lb chicken breast, a dozen eggs") and matches each with the matcher.

Either way the result is a *draft*: the UI shows it for editing before it
becomes the Plan page's shopping list.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from .catalog import Product
from .config import LLM_MODEL, demo_mode
from .extraction import FALLBACK_BETA
from .matching import ProductMatcher
from .units import SIZE_RE, parse_size, same_dimension

NONE_CHOICE = "NONE"
MAX_TOOL_ROUNDS = 6
# A shopping list is reviewed before use, so accept a looser match than for receipts
# (85), but say so in the line's note.
CLOSE_MATCH_SCORE = 60.0


class ListAssistantError(RuntimeError):
    """Raised with a message that is safe to show to the user."""


@dataclass(frozen=True)
class ListLine:
    request: str             # what the user (or recipe) asked for, e.g. "1 lb ground beef"
    product: str | None      # canonical product, or None if nothing in the catalog fits
    quantity: float          # in the product's unit
    unit: str                # the product's unit ("" when unmatched)
    note: str = ""


@dataclass
class ListDraft:
    lines: list[ListLine]
    source: str              # "llm" or "demo"
    notes: list[str] = field(default_factory=list)


class ListAssistant(Protocol):
    def build(self, text: str) -> ListDraft: ...


# ----- offline assistant ------------------------------------------------------------

# Per-serving amounts in each product's unit. Deliberately small: enough to demo.
RECIPES: dict[str, list[tuple[str, float]]] = {
    "tacos": [("ground beef (85/15)", 0.25), ("cheddar cheese", 1.0), ("roma tomato", 0.125),
              ("yellow onion", 0.1), ("avocado (hass)", 0.5), ("black beans (canned)", 4.0),
              ("tortilla chips", 2.0)],
    "spaghetti": [("pasta (spaghetti)", 4.0), ("ground beef (85/15)", 0.25),
                  ("roma tomato", 0.25), ("yellow onion", 0.1), ("olive oil (extra virgin)", 0.5)],
    "salmon dinner": [("salmon fillet (atlantic)", 0.4), ("rice (jasmine)", 3.0),
                      ("frozen broccoli", 4.0), ("butter (unsalted)", 0.5)],
}
_RECIPE_RE = re.compile(r"^\s*(?P<dish>[a-z ]+?)\s+for\s+(?P<n>\d+)\s*$", re.IGNORECASE)
_LEADING_COUNT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+(?!x\b)")
_FILLER = re.compile(r"^\s*(a|an|some|of)\s+", re.IGNORECASE)


class DemoListAssistant:
    def __init__(self, catalog: list[Product], matcher: ProductMatcher) -> None:
        self.units = {p.name: p.unit for p in catalog}
        self.matcher = matcher

    def build(self, text: str) -> ListDraft:
        lines: list[ListLine] = []
        for chunk in (c.strip() for c in re.split(r"[\n,;]+", text)):
            if not chunk:
                continue
            recipe = _RECIPE_RE.match(chunk)
            if recipe and recipe["dish"].lower() in RECIPES:
                servings = int(recipe["n"])
                for product, per_serving in RECIPES[recipe["dish"].lower()]:
                    if product in self.units:
                        lines.append(ListLine(chunk, product, round(per_serving * servings, 2),
                                              self.units[product], f"{recipe['dish']} for {servings}"))
            else:
                lines.append(self._parse_item(chunk))
        notes = ["Offline mode: known recipes are " + ", ".join(sorted(RECIPES))
                 + "; anything else is matched one item per line or comma."]
        return ListDraft(lines, "demo", notes)

    def _parse_item(self, chunk: str) -> ListLine:
        size = parse_size(chunk)                       # "2 lb", "16 oz", "dozen"
        name = SIZE_RE.sub(" ", chunk)
        name = re.sub(r"\b(dozen|doz)\b", " ", name, flags=re.IGNORECASE)
        count_match = _LEADING_COUNT.match(name)       # "3 avocados"
        count = float(count_match.group(1)) if count_match else None
        name = _FILLER.sub("", _LEADING_COUNT.sub("", name)).strip()

        match = self.matcher.match(name)
        product, note = match.product, ""
        if product is None and match.candidates and match.candidates[0][1] >= CLOSE_MATCH_SCORE:
            product, note = match.candidates[0][0], "closest match; please check"
        if product is None:
            return ListLine(chunk, None, 0.0, "", "no matching product in the catalog")
        unit = self.units[product]
        if size is not None and same_dimension(size.unit, unit):
            return ListLine(chunk, product, round(size.to(unit), 3), unit, note)
        if size is None and count is not None and unit == "each":
            return ListLine(chunk, product, count, unit, note)
        if size is None and count is None:
            return ListLine(chunk, product, 1.0, unit, note or "quantity assumed; please check")
        return ListLine(chunk, product, count or 1.0, unit,
                        f"couldn't convert to {unit}; please check the quantity")


# ----- LLM assistant ------------------------------------------------------------------

SYSTEM_PROMPT = """You turn recipes, meal ideas and free-text grocery lists into a shopping list
for a price-comparison app. Only products in the app's catalog can be priced.

Use the search_catalog tool to find the catalog product for each ingredient before you answer;
search with plain ingredient names such as "ground beef" or "tomatoes". Quantities must be in
the product's unit that search_catalog returns (lb, oz, fl_oz, gal or each). For a dish, estimate
reasonable amounts for the number of servings asked for. Pantry staples like salt and spices
that the catalog doesn't carry should use product "NONE" with a short note."""

SEARCH_TOOL = {
    "name": "search_catalog",
    "description": "Search the grocery catalog. Returns up to 5 products (name, unit, category) "
                   "with a 0-100 similarity score, best first.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "An ingredient name"}},
        "required": ["query"],
        "additionalProperties": False,
    },
}


def answer_schema(product_names: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string"},
                        "product": {"type": "string", "enum": [*product_names, NONE_CHOICE]},
                        "quantity": {"type": "number"},
                        "note": {"type": "string"},
                    },
                    "required": ["request", "product", "quantity", "note"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    }


class LLMListAssistant:
    def __init__(self, catalog: list[Product], matcher: ProductMatcher,
                 client: Any | None = None, model: str = LLM_MODEL) -> None:
        self.products = {p.name: p for p in catalog}
        self.matcher = matcher
        self._client = client  # injectable so tests can pass a fake
        self.model = model

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def search_catalog(self, query: str) -> list[dict[str, Any]]:
        """The tool the model calls. Runs locally against our catalog."""
        return [{"name": name, "unit": self.products[name].unit,
                 "category": self.products[name].category, "score": score}
                for name, score in self.matcher.rank(query, top_k=5)]

    def build(self, text: str) -> ListDraft:
        if not self.model:
            raise ListAssistantError("No model configured. Set GROCERY_LLM_MODEL.")
        messages: list[dict[str, Any]] = [{"role": "user", "content": text}]
        schema = answer_schema(sorted(self.products))
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = self.client.beta.messages.create(
                    model=self.model, max_tokens=16000, system=SYSTEM_PROMPT,
                    tools=[SEARCH_TOOL], messages=messages,
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                    betas=[FALLBACK_BETA], fallbacks="default",
                )
            except anthropic.APIConnectionError as exc:
                raise ListAssistantError("Could not reach the Anthropic API.") from exc
            except anthropic.APIStatusError as exc:
                raise ListAssistantError(f"Anthropic API error {exc.status_code}.") from exc

            if response.stop_reason == "tool_use":
                # Keep the model's turn, run every tool call, send all results back together.
                messages.append({"role": "assistant", "content": response.content})
                results = [{"type": "tool_result", "tool_use_id": block.id,
                            "content": json.dumps(self.search_catalog(block.input["query"]))}
                           for block in response.content if block.type == "tool_use"]
                messages.append({"role": "user", "content": results})
                continue
            if response.stop_reason == "refusal":
                raise ListAssistantError("The model declined this request.")
            if response.stop_reason == "max_tokens":
                raise ListAssistantError("The answer was cut off. Try a shorter list.")
            text_out = next((b.text for b in response.content if b.type == "text"), None)
            if text_out is None:
                raise ListAssistantError("The model returned no answer.")
            return self._to_draft(json.loads(text_out))
        raise ListAssistantError("Too many catalog searches; try a shorter list.")

    def _to_draft(self, answer: dict[str, Any]) -> ListDraft:
        lines = []
        for item in answer["items"]:
            product = self.products.get(item["product"])  # "NONE" (or anything unknown) -> None
            quantity = max(float(item["quantity"]), 0.0)
            lines.append(ListLine(item["request"], product.name if product else None,
                                  quantity if product else 0.0,
                                  product.unit if product else "", item.get("note", "")))
        return ListDraft(lines, "llm")


def get_list_assistant(catalog: list[Product], matcher: ProductMatcher) -> ListAssistant:
    """The LLM assistant when an API key is configured, otherwise the offline one."""
    if demo_mode():
        return DemoListAssistant(catalog, matcher)
    return LLMListAssistant(catalog, matcher)
