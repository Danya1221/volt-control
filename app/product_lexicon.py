"""Deterministic product vocabulary for supplier lists.

Only vocabulary is normalised: model numbers, regional hardware and SIM
configuration are never inferred. Unknown/contradictory identities stay visible
to the caller rather than being silently changed to a popular product.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


# Aliases are deliberately explicit. Unrestricted fuzzy matching would turn
# unfamiliar SKUs and accessories into unrelated phones.
ALIASES = {
    'iphone': ('айфон', 'айфоны', 'айфона', 'аифон', 'ифон', 'iphon', 'ipone', 'iphne', 'айфоон'),
    'ipad': ('айпад', 'айпэд', 'ипад', 'айпады'),
    'macbook': ('макбук', 'макбуки', 'макбукк', 'mac book', 'macbok'),
    'airpods': ('аирподс', 'аирподсы', 'эйрподс', 'эйрподсы', 'аирподз', 'air pods', 'airpds'),
    'apple': ('эппл', 'эпл', 'апл', 'aplle', 'appel'),
    'samsung': ('самсунг', 'самсунги', 'самсун', 'самсунгг', 'сасунг', 'самсун', 'самснг', 'samsng', 'sumsung', 'samsun', 'samsumg'),
    'galaxy': ('галакси', 'гэлакси', 'галакси'),
    'xiaomi': ('сяоми', 'сяоми', 'ксяоми', 'ксиаоми', 'ксиоми', 'сяомии', 'ксями', 'xiaomy', 'xiomi', 'xaiomi'),
    'redmi': ('редми', 'рэдми', 'редмик', 'redmy'),
    'poco': ('поко', 'покафон', 'покофон', 'pocophone', 'poko'),
    'realme': ('реалми', 'реалме', 'рилми', 'realmi'),
    'vivo': ('виво', 'vivо'),
    'oppo': ('оппо', 'орро'),
    'honor': ('хонор', 'онор', 'хоноры', 'хонер', 'honоr'),
    'huawei': ('хуавей', 'хуавэй', 'huawei'),
    'oneplus': ('ванплас', 'ванплюс', 'уанплас', 'уанплюс', 'one plus', 'onepluss'),
    'nothing': ('насинг', 'натинг', 'ноусинг', 'noting'),
    'google': ('гугл', 'гугль'),
    'pixel': ('пиксель', 'пиксел', 'пиксели', 'пиксельь', 'pixell'),
    'fitbit': ('фитбит',),
    'sony': ('сони', 'soni'),
    'sennheiser': ('сенхайзер', 'зенхайзер', 'сенхейзер', 'sennheizer'),
    'ray-ban': ('рейбан', 'рэйбан', 'рей бэн', 'рэй бэн', 'рей бен', 'рей бан', 'рэй бан', 'райбан', 'рай бан', 'rayban', 'ray ban', 'ray–ban'),
    'meta': ('мета',),
    'oakley': ('оукли', 'окли', 'оакли'),
    'fujifilm': ('фуджифильм', 'фуджифилм', 'фуджи', 'fuji film'),
    'instax': ('инстакс', 'инстакc'),
    'insta360': ('инста360', 'инста 360', 'инста', 'insta 360', 'insta-360'),
    'gopro': ('гоупро', 'гоу про', 'го про', 'гопро', 'go pro'),
    'dji': ('диджиай', 'ди джи ай', 'диджай'),
    'nintendo': ('нинтендо', 'нинтэндо', 'ниндентдо', 'nintedo'),
    'switch': ('свитч', 'свич'),
    'playstation': ('плейстейшн', 'плейстейшен', 'плей стейшн', 'play station'),
    'xbox': ('иксбокс', 'икс бокс', 'x box'),
    'dyson': ('дайсон', 'даисон', 'дайсоны', 'daison'),
    'dreame': ('дрими', 'дрим', 'дриме', 'dreamе'),
    'roborock': ('роборок', 'роборокк'),
    'coros': ('корос',),
    'garmin': ('гармин', 'гармины'),
    'oura': ('оура',),
    'netgear': ('нетгир', 'нетгеар'),
    'yandex': ('яндекс',),
    'marshall': ('маршал', 'маршалл'),
    'jbl': ('джибиэль', 'джбл', 'джейбиэл'),
    'bose': ('боуз', 'бозе'),
    'bowers & wilkins': ('бауэрс', 'bowers wilkins'),
    'beats': ('битс',),
    'anker': ('анкер',),
    'baseus': ('басеус', 'базеус'),
    'ugreen': ('югрин',),
    'logitech': ('лоджитек', 'логитек'),
    'razer': ('рейзер', 'рэйзер'),
    'asus': ('асус',),
    'lenovo': ('леново',),
    'acer': ('эйсер', 'асер'),
    'dell': ('делл',),
    'msi': ('эмэсай',),
}

_REPLACEMENTS = sorted(
    ((alias, target) for target, aliases in ALIASES.items() for alias in aliases if alias != target),
    key=lambda pair: len(pair[0]), reverse=True,
)
_ALIASES_RE = re.compile('|'.join(r'(?<!\w)' + re.escape(a) + r'(?!\w)' for a, _ in _REPLACEMENTS), re.I)
_ALIASES_LOOKUP = {alias.casefold(): target for alias, target in _REPLACEMENTS}
_PHONE_PREFIXES = ('iphone', 'ipad', 'pixel', 'redmi', 'poco', 'oneplus', 'honor', 'xiaomi', 'realme', 'vivo')
_JOINED_PHONE_PREFIX = re.compile(
    r'(?<!\w)(' + '|'.join(re.escape(token) for family in _PHONE_PREFIXES
                           for token in (family, *ALIASES.get(family, ()))) + r')(?=\d)', re.I)


def normalize_product_name(text: str) -> str:
    """Resolve known lexical forms, retaining every model/version number."""
    value = unicodedata.normalize('NFKC', text).replace('ё', 'е').replace('Ё', 'Е')
    value = _JOINED_PHONE_PREFIX.sub(r'\1 ', value)
    value = _ALIASES_RE.sub(lambda m: _ALIASES_LOOKUP[m[0].casefold()], value)
    # Model-letter transliteration is limited to branded model contexts.
    for brand, letters in (('poco', {'ф': 'f', 'х': 'x', 'м': 'm', 'с': 'c'}),
                           ('samsung', {'с': 's', 'а': 'a', 'м': 'm'}),
                           ('galaxy', {'с': 's', 'а': 'a', 'м': 'm'})):
        value = re.sub(r'(?i)(\b' + brand + r'\s+)([фхмса])(?=\s*\d)',
                       lambda m: m[1] + letters.get(m[2].casefold(), m[2]), value)
    return re.sub(r'\s+', ' ', value).strip()


@dataclass(frozen=True)
class ProductIdentity:
    brand: str | None
    category: str
    family: str | None
    normalized: str
    issues: tuple[str, ...] = ()


BRAND_PATTERNS = {
    'Apple': r'\b(?:apple|iphone|ipad|macbook|airpods|imac|mac\s+mini|mac\s+studio)\b',
    'Samsung': r'\b(?:samsung|galaxy)\b',
    'Xiaomi': r'\b(?:xiaomi|redmi|poco)\b',
    'Realme': r'\brealme\b', 'Vivo': r'\bvivo\b', 'OPPO': r'\boppo\b',
    'Honor': r'\bhonor\b', 'Huawei': r'\bhuawei\b', 'OnePlus': r'\boneplus\b',
    'Nothing': r'\bnothing\b', 'Google': r'\b(?:google|pixel)\b', 'Fitbit': r'\bfitbit\b',
    'Sony': r'\b(?:sony|wh[- ]?1000xm\d+|wf[- ]?1000xm\d+)\b',
    'Sennheiser': r'\bsennheiser\b', 'Meta Ray-Ban': r'\bray[- ]?ban\b',
    'Meta Oakley': r'\boakley\b', 'Meta': r'\bmeta\b',
    'Fujifilm': r'\b(?:fujifilm|instax)\b', 'Insta360': r'\binsta360\b',
    'GoPro': r'\bgopro\b', 'DJI': r'\bdji\b', 'Nintendo': r'\b(?:nintendo|switch)\b',
    'Microsoft': r'\b(?:microsoft|xbox)\b', 'Dyson': r'\bdyson\b',
    'Dreame': r'\bdreame\b', 'Roborock': r'\broborock\b',
    'Coros': r'\bcoros\b', 'Garmin': r'\bgarmin\b', 'Oura': r'\boura\b',
    'Netgear': r'\bnetgear\b', 'Яндекс': r'\b(?:yandex|алиса)\b',
    'Marshall': r'\bmarshall\b', 'JBL': r'\bjbl\b', 'Bose': r'\bbose\b',
    'Bowers & Wilkins': r'\bbowers\s*(?:&\s*)?wilkins\b', 'Beats': r'\bbeats\b',
    'Anker': r'\banker\b', 'Baseus': r'\bbaseus\b', 'UGREEN': r'\bugreen\b',
    'Logitech': r'\blogitech\b', 'Razer': r'\brazer\b', 'ASUS': r'\basus\b',
    'Lenovo': r'\blenovo\b', 'Acer': r'\bacer\b', 'Dell': r'\bdell\b', 'MSI': r'\bmsi\b',
}


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def recognize_product(text: str) -> ProductIdentity:
    """Recognise an explicit brand/family without inferring regional hardware."""
    normalized = normalize_product_name(text)
    n = normalized.casefold()
    # Compatibility targets do not identify the accessory's manufacturer.
    core = re.split(r'\b(?:для|for|compatible\s+with)\b', n, maxsplit=1)[0]
    brands = {brand for brand, pattern in BRAND_PATTERNS.items() if _has(pattern, core)}
    if 'Meta' in brands and brands.intersection({'Meta Ray-Ban', 'Meta Oakley'}):
        brands.remove('Meta')
    if 'Fitbit' in brands and 'Google' in brands:
        brands.remove('Fitbit')
    # PlayStation is a Sony product, but bare "Sony" does not mean PlayStation.
    if _has(r'\bplaystation\b', core):
        brands.add('Sony')
    # Brandless Note entries are the Redmi Note line in the supplied price list.
    # Do not override an explicit competing manufacturer such as Galaxy Note.
    if not brands and _has(r'^\s*(?:[•*]\s*)?note\s+(?:14s?|15|17)\b', core):
        brands.add('Xiaomi')
    brand = next(iter(brands)) if len(brands) == 1 else None
    issues = ('Указаны несовместимые бренды: ' + ', '.join(sorted(brands)),) if len(brands) > 1 else ()
    family = None
    category = 'Другое'

    # Explicit standalone accessories take precedence over compatible devices.
    if _has(r'\b(?:case|cover|protector|cable|adapter|charger|power\s*bank|powerbank|'
            r'solar\s+panel|mppt)\b|чехол|защитн\w*\s+(?:стекло|пленк)|кабел|адаптер|'
            r'зарядн|солнечн\w*\s+панел|пауэрбанк|повербанк', core):
        # Watch cases are part of the complete watch title, not separate covers.
        watch_case = (_has(r'\bwatch\b', core) and _has(r'\b(?:aluminum|aluminium|titanium|steel|polished|satin)\b', core)
                      and not _has(r'\b(?:cover|protector|protective)\b|чехол', core))
        if not watch_case:
            charging = _has(r'\b(?:charger|adapter|power\s*bank|powerbank|solar\s+panel|mppt)\b|зарядн|адаптер|панел|пауэрбанк|повербанк', core)
            return ProductIdentity(brand, 'Зарядные устройства' if charging else 'Аксессуары', 'accessory', normalized, issues)

    rules = [
        ('Планшеты', 'tablet', r'\b(?:ipad|tablet|pad)\b|\b(?:galaxy|samsung)\s+tab\b|планшет'),
        ('Ноутбуки', 'laptop', r'\b(?:macbook|laptop|notebook|galaxy\s+book|zenbook|vivobook|thinkpad|ideapad|aspire)\b|ноутбук'),
        ('Умные часы', 'watch', r'\b(?:watch\d*|smartwatch|coros|fenix\s+\d|forerunner|venu)\b|смарт.?часы'),
        ('Умные кольца', 'ring', r'\b(?:ring|oura)\b|умн\w*\s+кольц'),
        ('Наушники', 'headphones', r'\b(?:airpods|buds|headphones|earbuds|headset|wh[- ]?1000xm\d+|wf[- ]?1000xm\d+|hd\s*620s|quietcomfort)\b|наушник'),
        ('Микрофоны', 'microphone', r'\b(?:mic|microphone|wave|transmitter)\b|микрофон'),
        ('Веб-камеры', 'webcam', r'\b(?:webcam|link\s+2(?:c)?(?:\s+pro)?)\b|веб.?камер'),
        ('Игровые приставки', 'console', r'\b(?:nintendo|switch|playstation|xbox)\b|приставк'),
        ('Очки', 'glasses', r'\b(?:ray[- ]?ban|oakley|wayfarer|headliner|skyler|scriber|blayzer)\b|умн\w*\s+очки'),
        ('Камеры', 'camera', r'\b(?:fujifilm|instax|gopro|insta360|osmo\s+(?:pocket|360|action)|ace\s*pro|gimbal\s+camera)\b|экшен.?камер'),
        ('Портативные электростанции', 'power_station', r'\bdji\s+power\s+\d'),
        ('Уход за волосами', 'haircare', r'\b(?:airwrap|supersonic|airstrait|corrale)\b|фен|стайлер|выпрямител'),
        ('Пылесосы', 'vacuum', r'\b(?:vacuum|roborock|dreame\s+[a-z]\d+|dyson\s+v\d+)\b|пылесос'),
        ('Колонки', 'speaker', r'\b(?:speaker|emberton|stanmore|kilburn|woburn|flip\s+\d|charge\s+\d)\b|\b(?:yandex|алиса)\b|колонк'),
        ('Сетевое оборудование', 'network', r'\b(?:netgear|router|ethernet)\b|роутер|маршрутизатор|коммутатор'),
        ('Фитнес-браслеты', 'fitness_tracker', r'\bfitbit\b'),
        ('Навигаторы', 'navigation', r'\bgarmin\s+edge\s+\d+\b'),
        ('Аксессуары', 'tracker', r'\b(?:smarttag\d*|airtag\d*)\b'),
    ]
    for label, product_family, pattern in rules:
        if _has(pattern, core):
            category, family = label, product_family
            break
    else:
        phone = _has(r'\b(?:iphone|pixel\s+\d+|nothing\s+phone|redmi|poco|note\s+\d+)\b', core)
        phone |= brand in {'Honor', 'OnePlus', 'Realme', 'Vivo', 'OPPO', 'Huawei'} and _has(r'\d', core)
        phone |= brand == 'Xiaomi' and _has(r'\bxiaomi\s+(?:mix\s+flip|\d)', core)
        phone |= brand == 'Samsung' and _has(r'\b(?:[as]\d{2}[a-z]?|z\s+(?:flip|fold)\s*\d+|note\s*\d+)\b', core)
        if phone:
            category, family = 'Смартфоны', 'phone'
        elif brand == 'Meta':
            issues += ('Укажите линейку очков Meta: Ray-Ban или Oakley',)
    return ProductIdentity(brand, category, family, normalized, issues)

