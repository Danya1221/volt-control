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


# Restrict this policy to resolved @hi_catalog_bot sources. Unknown entries are reviewed.
HI_ACCESSORY = re.compile(r"^\s*(?:аксессуар|чехол|стекло|плёнк|пленк|заряд|кабель|adapter|charger|case|cover|cable)", re.I)
HI_OTHER = re.compile(r"(?:\b(?:ipad|macbook|laptop|tablet|airpods|headphones|earbuds|headset|wh-1000\w*|smartwatch|insta360|dji|nintendo|playstation|xbox|dyson|gopro|ray[ -]?ban|oakley|instax)\b|(?:apple|galaxy|pixel|samsung|huawei)\s+watch\b|(?:galaxy|samsung)\s+tab\b|наушник|планшет|ноутбук|приставк|фен|смарт.?часы)", re.I)
HI_IPHONE = re.compile(r"(?:\biphone\b|айфон)", re.I)
HI_ANDROID = re.compile(r"(?:\bandroid\b|андроид|\b(?:oneplus|redmi|poco|realme|oppo|vivo|motorola)\b|\b(?:samsung|galaxy)\s+(?:galaxy\s+)?[aszm]\s?\d+|\bpixel\s+\d+|\bnothing\s+phone\b|\bhonor\s+(?:magic|\d)|\bxiaomi\s+\d)", re.I)

def hi_kind(name):
    if HI_ACCESSORY.search(name):
        return 'other'
    android = bool(HI_ANDROID.search(name))
    iphone = bool(HI_IPHONE.search(name))
    if android and iphone:
        return 'uncertain'
    if android:
        return 'android'
    if iphone:
        return 'iphone'
    if HI_OTHER.search(name):
        return 'other'
    return 'uncertain'

def parse_lines(text: str, exclude_hi_android: bool = False):
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
        if exclude_hi_android:
            kind = hi_kind(name)
            if kind == 'android':
                ignored.append({"line": number, "raw": original, "reason": "Android-смартфоны этого поставщика исключены"})
                continue
            if kind == 'uncertain':
                review.append({"line": number, "raw": original, "reason": "Нельзя уверенно исключить Android-смартфон"})
                continue
        brand = next((key for key, pattern in BRANDS.items() if pattern.search(name)), None)
        if brand is None:
            review.append({"line": number, "raw": original, "reason": "Unknown brand"})
            continue
        category = ("Смартфоны" if PHONE.search(name) else "Планшеты" if TABLET.search(name)
                    else "Ноутбуки" if LAPTOP.search(name) else "Другое")
        if exclude_hi_android and hi_kind(name) == 'other' and category == 'Смартфоны':
            category = 'Другое'
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

