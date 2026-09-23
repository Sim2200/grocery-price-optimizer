"""Map raw receipt names onto canonical products.

Hybrid pipeline, cheapest and most trustworthy step first:

1. Alias table   - exact lookup of names the user (or an earlier run) already mapped.
2. Rules         - lowercase, expand receipt abbreviations (ORG -> organic,
                   BNLS -> boneless), strip store brands and package sizes.
3. Fuzzy match   - rapidfuzz similarity against canonical names + synonyms,
                   with the organic / conventional distinction enforced.
4. LLM fallback  - optional: ask the LLM to pick from the top fuzzy candidates.
5. Otherwise     - leave unmatched and flag for human review.

Anything below the acceptance threshold is flagged `needs_review`, and a
user correction is written back to the alias table so it is never asked again.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .catalog import Product
from .config import FUZZY_ACCEPT_THRESHOLD
from .units import SIZE_RE

# Receipt abbreviations -> words. Keys are matched as whole tokens.
ABBREVIATIONS: dict[str, str] = {
    "org": "organic", "orgnc": "organic", "og": "organic",
    "bnls": "boneless", "sknls": "skinless", "skls": "skinless",
    "chkn": "chicken", "chix": "chicken", "brst": "breast", "brsts": "breast",
    "whl": "whole", "wh": "whole", "grk": "greek", "ygrt": "yogurt", "yog": "yogurt",
    "pln": "plain", "chdr": "cheddar", "ched": "cheddar", "shrp": "sharp",
    "btr": "butter", "unsltd": "unsalted", "unslt": "unsalted",
    "grnd": "ground", "grd": "ground", "bf": "beef", "slmn": "salmon",
    "atl": "atlantic", "flt": "fillet", "fil": "fillet", "ww": "whole wheat",
    "brd": "bread", "spag": "spaghetti", "jsmn": "jasmine", "jasm": "jasmine",
    "pb": "peanut butter", "crmy": "creamy", "blk": "black", "bns": "beans",
    "evoo": "extra virgin olive oil", "oj": "orange juice", "almd": "almond",
    "unswt": "unsweetened", "unswtnd": "unsweetened", "frz": "frozen", "fzn": "frozen",
    "broc": "broccoli", "hmms": "hummus", "clsc": "classic", "cof": "coffee",
    "tort": "tortilla", "chps": "chips", "strwb": "strawberries", "strawb": "strawberries",
    "blueb": "blueberries", "blubry": "blueberries", "avo": "avocado", "avoc": "avocado",
    "spin": "spinach", "bby": "baby", "ylw": "yellow", "yel": "yellow", "onn": "onion",
    "tom": "tomato", "toms": "tomatoes", "carr": "carrots", "lg": "large", "lrg": "large",
    "mlk": "milk", "rf": "reduced fat", "bnna": "banana", "ban": "banana",
    "xvoo": "extra virgin olive oil", "pnt": "peanut", "gr": "grade",
}

# Store / private-label brand words that carry no product meaning.
BRAND_NOISE: tuple[str, ...] = (
    "trader joe's", "trader joes", "tj's", "tjs", "tj", "simply nature", "friendly farms",
    "happy farms", "specially selected", "millville", "clancy's", "clancys", "lidl",
    "preferred selection", "giant", "gnt", "nature's promise", "natures promise",
    "good & gather", "good and gather", "market pantry", "great value", "kirkland",
    "365", "aldi", "target",
)


def normalize_alias_key(raw_name: str) -> str:
    """Key used for alias-table lookups: lowercase, single spaces, no punctuation."""
    text = re.sub(r"[^a-z0-9%/ ]+", " ", raw_name.lower())
    return re.sub(r"\s+", " ", text).strip()


def clean_name(raw_name: str) -> str:
    """Rules step: turn 'TJ ORG BANANAS 3 LB' into 'organic bananas'."""
    text = raw_name.lower()
    text = SIZE_RE.sub(" ", text)  # drop package sizes like "16 oz"
    for brand in BRAND_NOISE:
        text = re.sub(rf"(?<![a-z]){re.escape(brand)}(?![a-z])", " ", text)
    text = re.sub(r"[^a-z0-9%/ ]+", " ", text)
    tokens = [ABBREVIATIONS.get(tok, tok) for tok in text.split()]
    return " ".join(" ".join(tokens).split())


def _strip_organic(text: str) -> str:
    return " ".join(tok for tok in text.split() if tok != "organic")


def _candidate_strings(product: Product) -> list[str]:
    """Searchable strings for a product, with parentheses and 'organic' removed."""
    names = [product.name, *product.synonyms]
    return [_strip_organic(re.sub(r"[()]", " ", n.lower())) for n in names]


def similarity(a: str, b: str) -> float:
    """0-100 score. Average of token-set (robust to extra words) and
    token-sort (penalises missing words) ratios, so 'milk' does not tie
    perfectly with both 'milk whole' and 'milk 2%'."""
    return 0.5 * fuzz.token_set_ratio(a, b) + 0.5 * fuzz.token_sort_ratio(a, b)


@dataclass
class MatchResult:
    raw_name: str
    product: str | None
    score: float
    method: str  # "alias" | "fuzzy" | "llm" | "unmatched"
    needs_review: bool
    candidates: list[tuple[str, float]] = field(default_factory=list)


# An LLM fallback receives the raw name and candidate product names and
# returns one of them or None.
LLMFallback = Callable[[str, list[str]], str | None]


class ProductMatcher:
    ORGANIC_MISMATCH_PENALTY = 20.0

    def __init__(
        self,
        catalog: list[Product],
        aliases: dict[str, str] | None = None,
        threshold: float = FUZZY_ACCEPT_THRESHOLD,
        llm_fallback: LLMFallback | None = None,
        use_rules: bool = True,
    ) -> None:
        self.catalog = catalog
        # use_rules=False skips abbreviation/brand/size cleanup (for ablation in the eval).
        self.use_rules = use_rules
        self.aliases = {normalize_alias_key(k): v for k, v in (aliases or {}).items()}
        self.threshold = threshold
        self.llm_fallback = llm_fallback
        self._products_by_name = {p.name: p for p in catalog}

    def add_alias(self, raw_name: str, product_name: str) -> None:
        self.aliases[normalize_alias_key(raw_name)] = product_name

    def rank(self, raw_name: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Score every catalog product against a raw name, best first."""
        cleaned = clean_name(raw_name) if self.use_rules else normalize_alias_key(raw_name)
        is_organic = "organic" in cleaned.split()
        query = _strip_organic(cleaned)
        scored: list[tuple[str, float]] = []
        for product in self.catalog:
            best = max(similarity(query, cand) for cand in _candidate_strings(product))
            if product.organic != is_organic:
                best -= self.ORGANIC_MISMATCH_PENALTY
            scored.append((product.name, round(max(best, 0.0), 1)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    def match(self, raw_name: str) -> MatchResult:
        key = normalize_alias_key(raw_name)
        if key in self.aliases and self.aliases[key] in self._products_by_name:
            return MatchResult(raw_name, self.aliases[key], 100.0, "alias", False)

        candidates = self.rank(raw_name)
        best_name, best_score = candidates[0] if candidates else (None, 0.0)
        if best_name is not None and best_score >= self.threshold:
            return MatchResult(raw_name, best_name, best_score, "fuzzy", False, candidates)

        if self.llm_fallback is not None:
            choice = self.llm_fallback(raw_name, [name for name, _ in candidates])
            if choice in self._products_by_name:
                # LLM picks are accepted but still surfaced for a quick check.
                return MatchResult(raw_name, choice, best_score, "llm", True, candidates)

        # No confident match. `candidates` still carries the best guesses so
        # the review UI can pre-select one.
        return MatchResult(raw_name, None, best_score, "unmatched", True, candidates)
