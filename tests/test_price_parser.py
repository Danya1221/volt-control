from app.price_parser import parse_lines

def test_smartphone_without_sim_goes_to_review():
    r=parse_lines("iPhone 17 Pro 256 Black — 85000")
    assert not r["candidates"]
    assert r["needs_review"][0]["reason"] == "Нужно проверить конфигурацию SIM"

def test_smartphone_with_sim_is_candidate_not_published():
    r=parse_lines("iPhone 17 Pro 256 Black eSIM — 85000")
    assert r["candidates"][0]["sim"] == "eSIM"
    assert r["candidates"][0]["cost"] == "85000"
    assert not r["can_publish"] and not r["complete"]

def test_unknown_brand_review():
    assert len(parse_lines("Mystery Phone 128 25000")["needs_review"]) == 1

def test_distinct_sim():
    a=parse_lines("iPhone 17 Pro 256 eSIM 85000")["candidates"][0]
    b=parse_lines("iPhone 17 Pro 256 2 SIM 87000")["candidates"][0]
    assert a["sim"] != b["sim"]

def test_nonprice_ignored():
    assert len(parse_lines("Прайс на сегодня")["ignored"]) == 1




def test_hi_policy_filters_android_but_keeps_iphone_and_other_items():
    text = '\n'.join(['iPhone 16 eSIM 60000', 'Samsung S25 eSIM 70000',
                      '16 Pro 256 Natural 75000', 'MacBook Air M3 80000',
                      'Samsung Galaxy Watch 7 35000', 'Sony WH-1000XM6 22000',
                      'Google Pixel 9 eSIM 65000'])
    result = parse_lines(text, exclude_hi_android=True)
    assert [r['line'] for r in result['ignored']] == [2, 7]
    assert [r['line'] for r in result['needs_review']] == [3]
    assert [r['line'] for r in result['candidates']] == [1, 4, 5, 6]
    assert parse_lines('Samsung Galaxy S25 eSIM 70000')['candidates']


def test_supplier_examples_are_recognised_without_guessing_conditions_or_sim():
    text = '\n'.join([
        '🎧AirPods MAX (USB-C) Midnight - 36300',
        '🎧AirPods 4 ANC - 10000',
        '(От 10шт ) - 9900',
        'SE3 40 Midnight(S/M) 2025 🇺🇸 - 17900',
        'UL 3 Black / Black/Charcoal TL(S/M) 🇺🇸 - 53200',
        '17 Pro 256 Silver (1Sim+eSim) - 99000',
        '17 Pro Max 256 Silver (eSim) - 99000',
        '17 Pro 512 Orange (Sim+Esim) ASIS🇭🇰 - 102500',
        '16 Pro 128 Black CPO 🇺🇸 - 70000',
        '15 128 Midnight 🇮🇳 - 52400',
        'iPad 11 128 Silver Wi-Fi 🇺🇸 - 37200',
        'AIR 11 M4 128 Starlight Wi-Fi 🇺🇸 - 59300',
        'Air 13 MDHA4 Starlight (M5 16/512) - 102300',
        'Samsung Galaxy S25 eSIM - 70000',
    ])
    r = parse_lines(text, exclude_hi_android=True)
    candidates = {x['line']: x for x in r['candidates']}
    review = {x['line']: x for x in r['needs_review']}
    ignored = {x['line']: x for x in r['ignored']}
    assert candidates[1]['brand'] == 'Apple' and candidates[1]['category'] == 'Наушники'
    assert candidates[2]['cost'] == '10000'
    assert candidates[4]['category'] == candidates[5]['category'] == 'Умные часы'
    assert review[6]['possible_iphone']['sim'] == 'SIM + eSIM'
    assert review[7]['possible_iphone']['sim'] == 'eSIM'
    assert review[6]['possible_iphone']['cost'] == '99000'
    assert 'possible_iphone' not in review[8] and 'Состояние' in review[8]['reason']
    assert 'possible_iphone' not in review[9] and 'Состояние' in review[9]['reason']
    assert 'possible_iphone' not in review[10] and 'SIM' in review[10]['reason']
    assert candidates[11]['category'] == candidates[12]['category'] == 'Планшеты'
    assert candidates[13]['category'] == 'Ноутбуки'
    assert 3 in ignored and 14 in ignored


def test_sim_conflicts_and_price_avoid_false_merges():
    r = parse_lines('iPhone 17 eSIM + 2 SIM - 99900')
    assert not r['candidates'] and r['needs_review']
    r = parse_lines('Sony WH-1000 22000')
    assert r['candidates'][0]['cost'] == '22000'
    r = parse_lines('iPhone 17 256 eSIM - 99 000')
    assert r['candidates'][0]['cost'] == '99000'
    assert not parse_lines('17 Pro 256 Silver eSIM - 99000')['candidates']
