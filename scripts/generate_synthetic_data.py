"""Generate SYNTHETIC grocery receipts for demos, tests and the eval harness.

Everything here is made up. Prices come from a hand-picked "typical" price
per product, a per-store price level, per-product noise and small drift
between visits. They are plausible, not real, and must not be read as actual
store prices. Store names are only used as labels.

Outputs (fixed random seed, so re-running gives identical files):
  data/synthetic/receipts/SYNTHETIC_<store>_<date>.json   ground-truth receipts
  data/synthetic/images/SYNTHETIC_<store>_<date>.png      rendered receipt images
  data/synthetic/SYNTHETIC_match_labels.json              raw_name -> true product
  evals/data/synthetic_noisy_predictions/*.json            fake "model output" with
                                                           injected errors, to demo the eval

Run:  python scripts/generate_synthetic_data.py
"""

from __future__ import annotations

import datetime as dt
import json
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "synthetic"
RECEIPTS_DIR = OUT / "receipts"
IMAGES_DIR = OUT / "images"
NOISY_DIR = ROOT / "evals" / "data" / "synthetic_noisy_predictions"

SEED = 7

# name -> (typical price, how it is sold, receipt abbreviation, plain name)
# how it is sold: "lb" = by weight (price is $/lb); otherwise a package size
# string and the price is per package.
PRODUCTS: dict[str, tuple[float, str, str, str]] = {
    "banana":                    (0.62, "lb", "BANANAS", "Bananas"),
    "banana (organic)":          (0.85, "lb", "ORG BANANAS", "Bananas, organic"),
    "apple (gala)":              (1.69, "lb", "GALA APPLES", "Apples Gala"),
    "avocado (hass)":            (1.19, "each", "HASS AVOCADO", "Avocado Hass"),
    "baby spinach (organic)":    (3.29, "5 oz", "ORG BBY SPINACH", "Baby spinach, organic"),
    "strawberries":              (3.49, "16 oz", "STRAWBERRIES", "Strawberries"),
    "blueberries":               (2.99, "6 oz", "BLUEBERRIES", "Blueberries"),
    "yellow onion":              (1.09, "lb", "YLW ONIONS", "Onions yellow"),
    "roma tomato":               (1.49, "lb", "ROMA TOMS", "Tomatoes Roma"),
    "carrots":                   (1.79, "2 lb", "CARROTS", "Carrots"),
    "milk (whole)":              (3.49, "1 gal", "WHL MILK", "Whole milk"),
    "milk (2%)":                 (3.39, "1 gal", "2% MILK", "Milk 2% reduced fat"),
    "eggs (large)":              (3.19, "12 ct", "LG EGGS", "Large eggs grade A"),
    "greek yogurt (plain)":      (5.49, "32 oz", "GRK YGRT PLN", "Greek yogurt plain"),
    "cheddar cheese":            (2.99, "8 oz", "SHRP CHDR", "Cheddar sharp"),
    "butter (unsalted)":         (4.49, "16 oz", "BTR UNSLTD", "Butter unsalted"),
    "chicken breast (boneless)": (3.99, "lb", "BNLS CHKN BRST", "Chicken breast boneless"),
    "ground beef (85/15)":       (5.49, "16 oz", "GRND BF 85/15", "Ground beef 85/15"),
    "salmon fillet (atlantic)":  (10.99, "lb", "ATL SALMON FLT", "Atlantic salmon fillet"),
    "bread (whole wheat)":       (2.79, "20 oz", "WW BREAD", "Whole wheat bread"),
    "pasta (spaghetti)":         (1.29, "16 oz", "SPAGHETTI", "Spaghetti"),
    "rice (jasmine)":            (3.49, "32 oz", "JASMINE RICE", "Jasmine rice"),
    "rolled oats":               (3.99, "42 oz", "OLD FASHIONED OATS", "Rolled oats"),
    "peanut butter (creamy)":    (2.49, "16 oz", "CRMY PB", "Peanut butter creamy"),
    "black beans (canned)":      (0.89, "15 oz", "BLK BEANS", "Black beans"),
    "olive oil (extra virgin)":  (6.99, "16.9 fl oz", "EVOO", "Extra virgin olive oil"),
    "orange juice":              (3.99, "52 fl oz", "OJ NFC", "Orange juice"),
    "almond milk (unsweetened)": (2.99, "64 fl oz", "ALMD MLK UNSWT", "Almond milk unsweetened"),
    "frozen broccoli":           (1.49, "12 oz", "FRZ BROCCOLI", "Broccoli florets frozen"),
    "hummus (classic)":          (2.99, "10 oz", "CLSC HUMMUS", "Hummus classic"),
    "coffee (ground)":           (6.49, "12 oz", "GRND COFFEE", "Ground coffee"),
    "tortilla chips":            (2.49, "13 oz", "TORT CHIPS", "Tortilla chips"),
}

# Synthetic store profiles: overall price level, how names are printed, first visit.
STORES = {
    "Aldi":         {"level": 0.86, "style": "abbr", "start": dt.date(2026, 6, 6)},
    "Lidl":         {"level": 0.90, "style": "plain", "start": dt.date(2026, 6, 9)},
    "Trader Joe's": {"level": 0.98, "style": "tj", "start": dt.date(2026, 6, 13)},
    "Giant":        {"level": 1.10, "style": "giant", "start": dt.date(2026, 6, 7)},
}
VISITS_PER_STORE = 4
DAYS_BETWEEN_VISITS = 28

# A few stores sell a different package size, so unit-price normalization matters.
SIZE_OVERRIDES = {
    ("Lidl", "eggs (large)"): "18 ct",
    ("Trader Joe's", "greek yogurt (plain)"): "16 oz",
    ("Giant", "rolled oats"): "18 oz",
    ("Aldi", "coffee (ground)"): "24 oz",
    ("Trader Joe's", "olive oil (extra virgin)"): "1 l",
}


def package_amount(size: str) -> tuple[float, str]:
    number, unit = re.match(r"([\d.]+)\s*(.+)", size).groups()
    return float(number), unit


def price_for_size(base_price: float, base_size: str, new_size: str) -> float:
    """Scale the package price to another size, with a small bulk discount."""
    base_amt, base_unit = package_amount(base_size)
    new_amt, new_unit = package_amount(new_size)
    to_common = {"oz": 1, "lb": 16, "ct": 1, "fl oz": 1, "l": 33.814, "gal": 128}
    ratio = (new_amt * to_common[new_unit]) / (base_amt * to_common[base_unit])
    return base_price * ratio * (0.92 if ratio > 1 else 1.0)


def printed_name(store: str, abbr: str, plain: str, size: str | None, rng: random.Random) -> str:
    style = STORES[store]["style"]
    if style == "plain":
        name = plain
        return f"{name} {size}" if size else name
    if style == "tj":
        name = f"TJ {abbr}" if rng.random() < 0.5 else abbr
    elif style == "giant":
        name = f"GNT {abbr}" if size else abbr
    else:
        name = abbr
    if size:
        compact = size.upper().replace(" ", "") if style == "abbr" else size.upper()
        name = f"{name} {compact}"
    return name


def build_store_catalog(rng: random.Random) -> dict[str, dict[str, dict]]:
    """For each store: which products it carries, package size and base price."""
    names = list(PRODUCTS)
    stores: dict[str, dict[str, dict]] = {}
    for store, profile in STORES.items():
        dropped = set(rng.sample(names, k=rng.randint(2, 4)))
        carried: dict[str, dict] = {}
        for name in names:
            if name in dropped:
                continue
            base, sold, _, _ = PRODUCTS[name]
            noise = math.exp(rng.gauss(0, 0.12))  # per-store, per-product price noise
            size = None if sold in ("lb", "each") else SIZE_OVERRIDES.get((store, name), sold)
            price = base * profile["level"] * noise
            if size and size != sold:
                price = price_for_size(base * profile["level"] * noise, sold, size)
            carried[name] = {"size": size, "sold_by": "lb" if sold == "lb" else "each",
                             "price": price}
        stores[store] = carried
    # Make sure every product is sold somewhere at least twice.
    for name in names:
        sellers = [s for s in stores if name in stores[s]]
        while len(sellers) < 2:
            store = next(s for s in STORES if s not in sellers)
            base, sold, _, _ = PRODUCTS[name]
            size = None if sold in ("lb", "each") else sold
            stores[store][name] = {"size": size, "sold_by": "lb" if sold == "lb" else "each",
                                   "price": base * STORES[store]["level"]}
            sellers.append(store)
    # TJ sells chicken as fixed-weight packs rather than by the pound.
    if "chicken breast (boneless)" in stores["Trader Joe's"]:
        stores["Trader Joe's"]["chicken breast (boneless)"]["sold_by"] = "pack"
    return stores


def make_receipt(store: str, date: dt.date, carried: dict[str, dict],
                 rng: random.Random) -> tuple[dict, dict[str, str]]:
    names = rng.sample(sorted(carried), k=min(len(carried), rng.randint(11, 16)))
    items, labels = [], {}
    for name in names:
        info = carried[name]
        _, _, abbr, plain = PRODUCTS[name]
        drift = math.exp(rng.gauss(0, 0.03))
        on_sale = rng.random() < 0.08
        price = info["price"] * drift * (0.85 if on_sale else 1.0)
        if info["sold_by"] == "lb":
            qty = round(rng.uniform(0.8, 3.5), 2)
            unit_price = round(price, 2)
            item = {"raw_name": printed_name(store, abbr, plain, None, rng), "quantity": qty,
                    "unit": "lb", "size": None, "unit_price": unit_price,
                    "line_total": round(qty * unit_price, 2)}
        elif info["sold_by"] == "pack":
            weight = round(rng.uniform(1.2, 2.2), 2)
            size = f"{weight} lb"
            unit_price = round(price * weight, 2)
            item = {"raw_name": printed_name(store, abbr, plain, size, rng), "quantity": 1,
                    "unit": "each", "size": size, "unit_price": unit_price,
                    "line_total": unit_price}
        else:
            qty = rng.choice([1, 1, 1, 2, 2, 3])
            unit_price = round(price, 2)
            item = {"raw_name": printed_name(store, abbr, plain, info["size"], rng), "quantity": qty,
                    "unit": "each", "size": info["size"], "unit_price": unit_price,
                    "line_total": round(qty * unit_price, 2)}
        items.append(item)
        labels[item["raw_name"]] = name
    total = round(sum(i["line_total"] for i in items), 2)
    return {"store": store, "date": date.isoformat(), "line_items": items, "total": total}, labels


# ----- rendering -------------------------------------------------------------

def _font(size: int) -> ImageFont.ImageFont:
    for path in ("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                 "C:/Windows/Fonts/consola.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def render_receipt(receipt: dict, path: Path) -> None:
    """Draw a plain thermal-printer style receipt."""
    width, char_w = 46, 12
    lines: list[str] = [
        receipt["store"].upper().center(width),
        "*** SYNTHETIC RECEIPT - NOT REAL ***".center(width),
        f"DATE {receipt['date']}".center(width),
        "-" * width,
    ]
    for item in receipt["line_items"]:
        name = item["raw_name"][:35]
        lines.append(f"{name:<36}{item['line_total']:>10.2f}")
        if item["unit"] == "lb":
            lines.append(f"   {item['quantity']:.2f} lb @ {item['unit_price']:.2f} /lb")
        elif item["quantity"] > 1:
            lines.append(f"   {int(item['quantity'])} @ {item['unit_price']:.2f}")
    lines += ["-" * width, f"{'TOTAL':<36}{receipt['total']:>10.2f}", "",
              "Generated for a demo. Prices are made up.".center(width)]
    font = _font(20)
    line_h = 26
    img = Image.new("RGB", (width * char_w + 60, len(lines) * line_h + 60), "white")
    draw = ImageDraw.Draw(img)
    for i, text in enumerate(lines):
        draw.text((30, 30 + i * line_h), text, fill="black", font=font)
    img.save(path)


# ----- noisy predictions for the eval demo -----------------------------------

def noisy_copy(receipt: dict, rng: random.Random) -> dict:
    """Simulate typical extraction mistakes so the eval harness has something to score."""
    pred = json.loads(json.dumps(receipt))
    items = pred["line_items"]
    if rng.random() < 0.5 and len(items) > 3:
        items.pop(rng.randrange(len(items)))  # missed a line
    for item in items:
        r = rng.random()
        if r < 0.06:
            item["unit_price"] = round(item["unit_price"] + 0.10, 2)  # misread digit
        elif r < 0.10:
            item["raw_name"] = item["raw_name"].replace("O", "0", 1)  # OCR-style typo
        elif r < 0.13:
            item["size"] = None  # dropped size
        elif r < 0.15:
            item["quantity"] = 1  # missed the weight
    if rng.random() < 0.25:
        items.append({"raw_name": "BAG FEE", "quantity": 1, "unit": "each", "size": None,
                      "unit_price": 0.10, "line_total": 0.10})  # hallucinated / non-product line
    if rng.random() < 0.2:
        pred["total"] = round(pred["total"] + 1.0, 2)
    return pred


def main() -> None:
    rng = random.Random(SEED)
    for directory in (RECEIPTS_DIR, IMAGES_DIR, NOISY_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        for old in directory.glob("SYNTHETIC_*"):
            old.unlink()

    catalogs = build_store_catalog(rng)
    labels: dict[str, str] = {}
    count = 0
    for store, profile in STORES.items():
        slug = re.sub(r"[^a-z]+", "", store.lower())
        for visit in range(VISITS_PER_STORE):
            date = profile["start"] + dt.timedelta(days=visit * DAYS_BETWEEN_VISITS)
            receipt, receipt_labels = make_receipt(store, date, catalogs[store], rng)
            labels.update(receipt_labels)
            stem = f"SYNTHETIC_{slug}_{date.isoformat()}"
            (RECEIPTS_DIR / f"{stem}.json").write_text(json.dumps(receipt, indent=2) + "\n")
            render_receipt(receipt, IMAGES_DIR / f"{stem}.png")
            (NOISY_DIR / f"{stem}.json").write_text(json.dumps(noisy_copy(receipt, rng), indent=2) + "\n")
            count += 1

    (OUT / "SYNTHETIC_match_labels.json").write_text(json.dumps(dict(sorted(labels.items())), indent=2) + "\n")
    print(f"Wrote {count} synthetic receipts, {len(labels)} distinct raw names, to {OUT}")


if __name__ == "__main__":
    main()
