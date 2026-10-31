"""Conservative supplier price-list parser.

Only parses unambiguous lines. Unknown products and SIM types go to manual review.
Parsing never publishes or applies a supplier batch automatically.
"""
import re
from decimal import Decimal
from app.product_lexicon import recognize_product, normalize_product_name

# Prefer a price after a visible separator; otherwise accept only a terminal integer.
PRICE_SEPARATED = re.compile(r"\s[-–—:]\s*(?P<price>\d{1,3}(?:[ \u00a0]\d{3})+|\d+)\s*(?:₽|руб\.?|р\.)?\s*$", re.I)
PRICE_SIMPLE = re.compile(r"(?<![\w])(?P<price>\d{3,})\s*(?:₽|руб\.?|р\.)?\s*$", re.I)
BULK = re.compile(r"^\s*\(?\s*от\s*\d+\s*(?:шт\.?|штук)\s*\)?", re.I)
SIM_COMBINED = re.compile(r"(?<!\w)(?:(?:1\s*)?sim\s*[+/]\s*esim|esim\s*[+/]\s*(?:1\s*)?sim)(?!\w)", re.I)
SIM_TWO = re.compile(r"(?<!\w)(?:2\s*sim|dual\s*sim)(?!\w)", re.I)
SIM_ESIM = re.compile(r"(?<!\w)esim(?!\w)", re.I)


def sim_configuration(name):
    remaining = re.sub(r'\b(?:е\s*сим|есим|е-сим|эсим|еsim)\b', 'esim', name, flags=re.I)
    remaining = re.sub(r'\bсим\b', 'sim', remaining, flags=re.I)
    hits = set()
    for label, pattern in [('SIM + eSIM', SIM_COMBINED), ('2 SIM', SIM_TWO), ('eSIM', SIM_ESIM)]:
        if pattern.search(remaining):
            hits.add(label)
            remaining = pattern.sub(' ', remaining)
    if re.search(r'(?<!\w)(?:1\s*sim|single\s*sim)(?!\w)', remaining, re.I):
        hits.add('1 SIM')
    return hits

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


# The supplied HI examples omit the brand for these specific product formats.
HI_IPHONE_SHORT = re.compile(r"^\s*(?:1[3-8](?:[eе])?)(?:\s+(?:pro(?:\s+max)?|plus|air))?\s+(?:128|256|512|1\s*tb|2\s*tb)\b", re.I)
HI_WATCH_SHORT = re.compile(r"^\s*(?:se\s*3|s(?:10|11|12))\s+(?:40|42|44|46)\b|^\s*ul\s*[23]\s+(?:black|natural)\b", re.I)
HI_IPAD_SHORT = re.compile(r"^\s*(?:air|pro)\s+(?:11|13)\s+m\d+\s+(?:128|256|512|1\s*tb|2\s*tb)\b.*\b(?:wi[ -]?fi|lte|cellular)\b", re.I)
HI_MAC_SHORT = re.compile(r"^\s*(?:air|pro|neo)\s+(?:13|14|15)\s+[a-z0-9]+\b.*\b(?:m[1-9](?:\s+(?:pro|max))?|a18\s+pro)\b.*\b\d+\s*/\s*(?:\d+|\d+tb)\b", re.I)
CONDITION = re.compile(r"(?<!\w)(?:cpo|asis|актив)(?!\w)", re.I)


def hi_short_kind(name):
    if HI_IPHONE_SHORT.search(name): return 'iphone'
    if HI_WATCH_SHORT.search(name): return 'watch'
    if HI_IPAD_SHORT.search(name): return 'ipad'
    if HI_MAC_SHORT.search(name): return 'macbook'
    return None

def _clean_line(line):
    return re.sub(r'^\s*[•▪▫◦·]\s*', '', line.replace('**', '').replace('__', '')).strip()


def _price_rows(text):
    """Pair supplier title/retail-price rows without mixing adjacent products."""
    lines = text.splitlines()
    consumed = set()
    tier = re.compile(r'^[\W_]*от\s+(\d+)\s*(?:шт\.?|штук)\s*[-–—:]\s*(.+)$', re.I)
    for index, original in enumerate(lines):
        if index in consumed:
            continue
        line = _clean_line(original)
        nxt = index + 1
        while nxt < len(lines) and not lines[nxt].strip():
            nxt += 1
        if line and nxt < len(lines) and not BULK.match(line):
            price = tier.match(_clean_line(lines[nxt]))
            simple = PRICE_SIMPLE.search(line)
            has_price = PRICE_SEPARATED.search(line) or (simple and simple['price'] not in {'128', '256', '512', '1024', '2048'})
            if price and price[1] == '1' and not has_price:
                consumed.add(nxt)
                yield index + 1, original + '\n' + lines[nxt], line + ' — ' + price[2]
                continue
        if tier.match(line):
            yield index + 1, original, 'От ' + tier.match(line)[1] + ' шт'
        else:
            yield index + 1, original, line


def parse_lines(text: str, exclude_hi_android: bool = False):
    accepted, review, ignored = [], [], []
    for number, original, line in _price_rows(text):
        if not line or line.startswith(("#", "//")):
            continue
        if BULK.match(line):
            ignored.append({"line": number, "raw": original, "reason": "Оптовая цена за количество"})
            continue
        match = PRICE_SEPARATED.search(line) or PRICE_SIMPLE.search(line)
        if not match:
            ignored.append({"line": number, "raw": original, "reason": "No terminal price"})
            continue
        value = match.group("price").replace(" ", "").replace("\u00a0", "")
        name = line[:match.start()].strip(" -–—:|")
        if not name or not value.isdecimal() or Decimal(value) <= 0:
            review.append({"line": number, "raw": original, "reason": "Invalid product or price"})
            continue
        normalized = normalize_product_name(name)
        identity = recognize_product(name)
        short_kind = hi_short_kind(normalized) if exclude_hi_android else None
        if exclude_hi_android:
            kind = 'other' if identity.family and identity.family != 'phone' else hi_kind(normalized)
            if kind == 'android':
                ignored.append({"line": number, "raw": original, "reason": "Android-смартфоны этого поставщика исключены"})
                continue
            if kind == 'uncertain' and not short_kind:
                review.append({"line": number, "raw": original, "reason": "Нельзя уверенно исключить Android-смартфон"})
                continue
        brand = 'Apple' if short_kind else identity.brand
        if identity.issues:
            review.append({'line': number, 'raw': original, 'reason': '; '.join(identity.issues)})
            continue
        if brand is None:
            review.append({"line": number, "raw": original, "reason": "Unknown brand"})
            continue
        if short_kind:
            prefix, category = {'iphone': ('iPhone', 'Смартфоны'), 'watch': ('Apple Watch', 'Умные часы'),
                                'ipad': ('iPad', 'Планшеты'), 'macbook': ('MacBook', 'Ноутбуки')}[short_kind]
            name = prefix + ' ' + name
        else:
            category = identity.category
        if CONDITION.search(name):
            review.append({"line": number, "raw": original, "reason": "Состояние товара требует проверки"})
            continue
        sim_hits = sim_configuration(name) if category == 'Смартфоны' else set()
        if category == "Смартфоны" and len(sim_hits) != 1:
            review.append({"line": number, "raw": original, "reason": "Нужно проверить конфигурацию SIM"})
            continue
        if len(sim_hits) > 1:
            review.append({"line": number, "raw": original, "reason": "Противоречивые обозначения SIM"})
            continue
        # Deliberately retain complete model text; no automatic SKU merging.
        candidate = {
            "line": number, "raw": original, "brand": brand,
            "model": name, "category": category,
            "sim": next(iter(sim_hits)) if sim_hits else "",
            "cost": str(Decimal(value)),
        }
        # A model number alone can also be an Android device: require explicit confirmation.
        if short_kind == 'iphone':
            review.append({"line": number, "raw": original, "reason": "Подтвердите, что это iPhone", "possible_iphone": candidate})
        else:
            accepted.append(candidate)
    return {"candidates": accepted, "needs_review": review, "ignored": ignored,
            "complete": False, "can_publish": False}

