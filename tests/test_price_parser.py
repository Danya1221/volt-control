from app.price_parser import parse_lines

def test_smartphone_without_sim_goes_to_review():
    r=parse_lines("iPhone 17 Pro 256 Black — 85000")
    assert not r["candidates"]
    assert r["needs_review"][0]["reason"] == "SIM configuration requires review"

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
