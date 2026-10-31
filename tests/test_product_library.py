"""Recognition examples drawn from the supplied supplier list.

These are isolated parser fixtures, never inventory seed data. Product names are
supplier labels; the tests do not assert that a model exists in the real world.
"""
import pytest

from app.price_parser import parse_lines


# Full, explicit identities from the list. Phone SIM is explicit so these cases
# exercise recognition rather than hardware inference from a country flag.
FAMILY_CASES = [
    ('Fujifilm instax Mini Evo Cinema', 'Fujifilm', 'Камеры'),
    ('Instax mini 13 Dreamy Blue', 'Fujifilm', 'Камеры'),
    ('Meta Ray-Ban Scriber Optics Gen2 S49 RW7002', 'Meta Ray-Ban', 'Очки'),
    ('Meta Ray-Ban Wayfarer Gen2 S50 RW4012', 'Meta Ray-Ban', 'Очки'),
    ('Meta Oakley HSTN S51 00W8002', 'Meta Oakley', 'Очки'),
    ('Яндекс Стрит Зеленая Алиса', 'Яндекс', 'Колонки'),
    ('Nintendo Switch Lite Gray', 'Nintendo', 'Игровые приставки'),
    ('Sony WH-1000XM6 Black', 'Sony', 'Наушники'),
    ('Sennheiser HD620S Black', 'Sennheiser', 'Наушники'),
    ('Google Pixel 11 Pro XL 512 Obsidian eSIM', 'Google', 'Смартфоны'),
    ('Google Pixel Watch 5 WI-FI 41mm Matte Black', 'Google', 'Умные часы'),
    ('Google Fitbit Air Berry Pink', 'Google', 'Фитнес-браслеты'),
    ('GoPro Max 2 8K 360', 'GoPro', 'Камеры'),
    ('Insta 360 Mic Air 1TX + 1RX', 'Insta360', 'Микрофоны'),
    ('Insta 360 Link 2C Standard Edition Graphite Black', 'Insta360', 'Веб-камеры'),
    ('Insta 360 AcePro 2 Single Battery Xplorer Bundle Silver', 'Insta360', 'Камеры'),
    ('Insta360 X6 Standart Bundle Midnight Black', 'Insta360', 'Камеры'),
    ('Insta 360 GO Ultra 4K White', 'Insta360', 'Камеры'),
    ('DJI Osmo Pocket 4P Vlog Combo', 'DJI', 'Камеры'),
    ('DJI Power 1000 Mini', 'DJI', 'Портативные электростанции'),
    ('Honor 600 Pro 12/512 Black VKP-NX9 2 SIM', 'Honor', 'Смартфоны'),
    ('Apple USB-C 20W Power Adapter A2347', 'Apple', 'Зарядные устройства'),
    ('iPhone 16 Pro Max 512 Black eSIM only', 'Apple', 'Смартфоны'),
    ('NOTHING Phone 4b 8/128 A009P Black 2 SIM', 'Nothing', 'Смартфоны'),
    ('OnePlus Nord 6 8/256 Pitch Black 2 SIM', 'OnePlus', 'Смартфоны'),
    ('OnePlus 15 5G 16/512 Ultra Violet 2 SIM', 'OnePlus', 'Смартфоны'),
    ('Galaxy S26 Ultra 12/512 Black SM-S948B/DS 2 SIM', 'Samsung', 'Смартфоны'),
    ('Galaxy Book 6 Pro NP940XJG - KG1IN', 'Samsung', 'Ноутбуки'),
    ('Galaxy Tab A11+ 8/256 Gray SM-X236B', 'Samsung', 'Планшеты'),
    ('Galaxy Buds 3 Pro Silver SM-R630', 'Samsung', 'Наушники'),
    ('Galaxy Watch9 44mm Silver SM-L350', 'Samsung', 'Умные часы'),
    ('Galaxy Ring SM-Q505 Titanium Gold 5', 'Samsung', 'Умные кольца'),
    ('Galaxy SmartTag2 Black EI-T5600', 'Samsung', 'Аксессуары'),
    ('Oura Ring 5 Size 8 Black', 'Oura', 'Умные кольца'),
    ('Redmi 17 6/128 Deep Blue NFC 2 SIM', 'Xiaomi', 'Смартфоны'),
    ('Xiaomi Pad 7 8/256 Green', 'Xiaomi', 'Планшеты'),
    ('Redmi Pad Pro 5G 6/128 Mint', 'Xiaomi', 'Планшеты'),
    ('Note 17 Pro Max 5G 8/512 Cloud Blush 2 SIM', 'Xiaomi', 'Смартфоны'),
    ('POCO F8 Ultra 12/256 Denim Blue slim 2 SIM', 'Xiaomi', 'Смартфоны'),
    ('POCO Pad X1 8/512 Grey', 'Xiaomi', 'Планшеты'),
    ('Redmi Watch 5 Lite Gold', 'Xiaomi', 'Умные часы'),
    ('Xiaomi wired screen display power bank 10000mAh 45W Green', 'Xiaomi', 'Зарядные устройства'),
    ('Vivo X300S 16/512 Purple 2 SIM', 'Vivo', 'Смартфоны'),
    ('Realme GT 7T 5G 12/512 Обсидиан 2 SIM', 'Realme', 'Смартфоны'),
    ('Realme Buds T200 Lite Storm Grey', 'Realme', 'Наушники'),
    ('Dreame Ultra Slim Magnetic Power Bank Air Power 17Pro', 'Dreame', 'Зарядные устройства'),
    ('Coros Pace 4 White Nylon', 'Coros', 'Умные часы'),
    ('Netgear ProSafe 48-Port GS752TP-300AUS', 'Netgear', 'Сетевое оборудование'),
    ('010-02694-04 GARMIN EDGE 540', 'Garmin', 'Навигаторы'),
    ('010-04763-01 GARMIN FENIX 9 51mm AMOLED Pebble Gray', 'Garmin', 'Умные часы'),
    ('Dyson Airwrap HS08 Strawberry Bronze', 'Dyson', 'Уход за волосами'),
]

ALIASES = [
    ('фуджифильм инстакс mini 13 Blue', 'Fujifilm', 'Камеры'),
    ('мета райбан Wayfarer Gen2 Black', 'Meta Ray-Ban', 'Очки'),
    ('рей бен Wayfarer Gen 2 Black', 'Meta Ray-Ban', 'Очки'),
    ('окли HSTN S51 Black', 'Meta Oakley', 'Очки'),
    ('ниндентдо Switch Lite Gray', 'Nintendo', 'Игровые приставки'),
    ('сони WH-1000XM6 Black', 'Sony', 'Наушники'),
    ('сенхайзер HD620S Black', 'Sennheiser', 'Наушники'),
    ('гугл пиксель 11 Pro 256 Obsidian есим', 'Google', 'Смартфоны'),
    ('го про Max 2 8K', 'GoPro', 'Камеры'),
    ('инста 360 X5 Essentials Bundle', 'Insta360', 'Камеры'),
    ('диджиай Osmo Pocket 4 Standard Combo', 'DJI', 'Камеры'),
    ('хонор 600 12/256 Black 2 сим', 'Honor', 'Смартфоны'),
    ('айфон 17 Pro 256 Black только есим', 'Apple', 'Смартфоны'),
    ('натинг Phone 4b 8/128 Blue 2 сим', 'Nothing', 'Смартфоны'),
    ('ванплас 15R 12/256 Mint Breeze 2 сим', 'OnePlus', 'Смартфоны'),
    ('сасунг с26 ультра 512 черный 2 сим', 'Samsung', 'Смартфоны'),
    ('сяоми 17T Pro 12/256 Deep Blue 2 сим', 'Xiaomi', 'Смартфоны'),
    ('редми Note 17 6/128 Black 2 сим', 'Xiaomi', 'Смартфоны'),
    ('поко ф8 ультра 12/256 черный 2 сим', 'Xiaomi', 'Смартфоны'),
    ('виво X300 16/512 Red 2 сим', 'Vivo', 'Смартфоны'),
    ('реалми GT 7T 12/512 Black 2 сим', 'Realme', 'Смартфоны'),
    ('дайсон Airwrap HS08 Strawberry Bronze', 'Dyson', 'Уход за волосами'),
]


@pytest.mark.parametrize('name,brand,category', FAMILY_CASES + ALIASES)
def test_product_family_is_recognised_with_brand_and_category(name, brand, category):
    result = parse_lines(name + ' — 22 700')
    assert len(result['candidates']) == 1, result
    row = result['candidates'][0]
    assert row['brand'] == brand
    assert row['category'] == category
    assert row['cost'] == '22700'
    assert not result['needs_review']
    assert result['can_publish'] is False and result['complete'] is False


def test_supplier_two_line_prices_keep_each_product_and_single_unit_price():
    result = parse_lines('**Цены на Все товары**\n'
                         '**• Instax mini 13 Dreamy Blue**\n'
                         '🇨🇳 От 1 шт - 8 800\n'
                         '🇨🇳 От 10 шт - 8 500\n'
                         '**• Sony WH-1000XM6 Black🇯🇵**\n'
                         '🇯🇵 От 1 шт - 25 200\n'
                         '**Galaxy Buds 3 Pro Silver SM-R630🇪🇺**\n'
                         '🇪🇺 От 1 шт - 10 900\n'
                         'Всего найдено 3 товаров')
    assert [row['brand'] for row in result['candidates']] == ['Fujifilm', 'Sony', 'Samsung']
    assert [row['cost'] for row in result['candidates']] == ['8800', '25200', '10900']
    assert result['candidates'][0]['line'] == 2
    assert result['candidates'][1]['line'] == 5
    assert result['candidates'][2]['line'] == 7


@pytest.mark.parametrize('name', [
    'iPhone 17 256 Black 🇺🇸',
    'Samsung Galaxy S26 Ultra 512 Black 🇭🇰',
    'OnePlus 15 12/512 Ultra Violet 🇺🇸',
])
def test_country_flag_does_not_invent_smartphone_sim_configuration(name):
    result = parse_lines(name + ' — 91 500')
    assert not result['candidates']
    assert len(result['needs_review']) == 1
    assert 'SIM' in result['needs_review'][0]['reason']


@pytest.mark.parametrize('name', [
    'UnknownBrand device 256',
    'iPhone Xiaomi 17 256 Black eSIM',
    'Samsung iPhone 17 256 Black eSIM',
])
def test_unknown_or_conflicting_brands_are_not_silently_published_as_one_brand(name):
    result = parse_lines(name + ' — 90 000')
    assert not result['candidates']
    assert result['needs_review']


def test_generations_versions_and_storage_survive_normalisation():
    result = parse_lines('поко F8 Ultra 12/256 Black 2 SIM - 51900\n'
                         'поко F9 Pro 12/512 White 2 SIM - 56500')
    assert len(result['candidates']) == 2
    a, b = result['candidates']
    assert 'f8' in a['model'].casefold() and 'ultra' in a['model'].casefold()
    assert 'f9' in b['model'].casefold() and 'pro' in b['model'].casefold()
    assert '12/256' in a['model'] and '12/512' in b['model']
    assert a['model'] != b['model']
