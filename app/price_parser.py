"""Conservative supplier price-list parser.

Only parses unambiguous lines. Unknown products and SIM types go to manual review.
Parsing never publishes or applies a supplier batch automatically.
"""
import re
from decimal import Decimal

PRICE = re.compile(r"(?P<price>\d[\d \u00a0]{2,})\s*(?:₽|руб\.?|р\.)?\s*$", re.I)
SIM = [
    ("SIM + eSIM", re.compile(r"(?<!\w)(?:sim\s*\+\s*esim|sim\s*/\s*esim)(?!\w)", re.I)),
    ("2 SIM", re.compile(r"(?<!\w)(?:2\s*sim|dual\s*sim)(?!\w)", re.I)),
    ("eSIM", re.compile(r"(?<!\w)esim(?!\w)", re.I)),
]
BRANDS = {
    "Apple": re.compile(r"\b(?:iphone|ipad|macbook|apple)\b", re.I),
    "Samsung": re.compile(r"\b(?:samsung|galaxy)\b", re.I),
    "Google": re.compile(r"\b(?:pixel|google)\b", re.I),
    "Sony": re.compile(r"\b(?:sony|wh-1000)\b", re.I),
    "Meta Ray-Ban": re.compile(r"\b(?:ray[ -]?ban|meta)\b", re.I),
    "Insta360": re.compile(r"\binsta360\b", re.I),
    "DJI": re.compile(r"\bdji\b", re.I),
    "Nintendo": re.compile(r"\b(?:nintendo|switch)\b", re.I),
}
PHONE = re.compile(r"\b(?:iphone|galaxy|pixel|oneplus|honor|nothing)\b", re.I)
TABLET = re.compile(r"\b(?:ipad|tablet|tab\s+s\d+)\b", re.I)
LAPTOP = re.compile(r"\b(?:macbook|laptop)\b", re.I)

def parse_lines(text: str):
    accepted, review, ignored = [], [], []
    for number, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        if not line or line.startswith(("#", "//")):
            continue
        match = PRICE.search(line)
        if not match:
            ignored.append({"line": number, "raw": original, "reason": "No terminal price"})
            continue
        value = match.group("price").replace(" ", "").replace("\u00a0", "")
        name = line[:match.start()].strip(" -–—:|")
        if not name or not value.isdecimal() or Decimal(value) <= 0:
            review.append({"line": number, "raw": original, "reason": "Invalid product or price"})
            continue
        brand = next((key for key, pattern in BRANDS.items() if pattern.search(name)), None)
        if brand is None:
            review.append({"line": number, "raw": original, "reason": "Unknown brand"})
            continue
        category = ("Смартфоны" if PHONE.search(name) else "Планшеты" if TABLET.search(name)
                    else "Ноутбуки" if LAPTOP.search(name) else "Другое")
        sim_hits = [label for label, pattern in SIM if pattern.search(name)]
        if category == "Смартфоны" and len(sim_hits) != 1:
            review.append({"line": number, "raw": original, "reason": "SIM configuration requires review"})
            continue
        if len(sim_hits) > 1:
            review.append({"line": number, "raw": original, "reason": "Ambiguous SIM configuration"})
            continue
        # Deliberately retain complete model text; no automatic SKU merging.
        accepted.append({
            "line": number, "raw": original, "brand": brand,
            "model": name, "category": category,
            "sim": sim_hits[0] if sim_hits else "",
            "cost": str(Decimal(value)),
        })
    return {"candidates": accepted, "needs_review": review, "ignored": ignored,
            "complete": False, "can_publish": False}
