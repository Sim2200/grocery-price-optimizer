"""Central configuration: file paths, model id and tunable defaults.

Everything can be overridden with environment variables so the same code
runs in tests, the CLI and the API.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent

# Canonical product catalog shipped with the package.
CATALOG_PATH = PACKAGE_DIR / "data" / "catalog.json"

# Bundled SYNTHETIC sample data (not real prices).
SYNTHETIC_DIR = PROJECT_ROOT / "data" / "synthetic"
SYNTHETIC_RECEIPTS_DIR = SYNTHETIC_DIR / "receipts"
SYNTHETIC_IMAGES_DIR = SYNTHETIC_DIR / "images"

DEFAULT_DB_PATH = Path(os.environ.get("GROCERY_DB", PROJECT_ROOT / "data" / "grocery.db"))

# Vision-capable model ID for receipt extraction and the optional matching fallback.
# Required for real (non-demo) extraction; there is no default.
LLM_MODEL = os.environ.get("GROCERY_LLM_MODEL", "")

# Ask the LLM to resolve product names the fuzzy matcher is unsure about (needs a key).
LLM_MATCHING = os.environ.get("GROCERY_LLM_MATCHING") == "1"

# Fuzzy-match score (0-100) at or above which a match is accepted automatically.
FUZZY_ACCEPT_THRESHOLD = 85.0

# Recency weighting: an observation this many days older than the newest one
# counts half as much.
PRICE_HALF_LIFE_DAYS = 30.0


def has_api_key() -> bool:
    """True when an Anthropic API key is available in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def demo_mode() -> bool:
    """Demo mode runs fully offline on bundled synthetic data.

    It is on when GROCERY_DEMO=1 or when no API key is configured.
    """
    return os.environ.get("GROCERY_DEMO") == "1" or not has_api_key()
