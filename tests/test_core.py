from app.main import ProductIn, key_for

def test_sim_is_distinct():
    p = ProductIn(brand='Apple', model='iPhone 17 Pro', category='Смартфоны', memory='256', color='Black', sim='eSIM')
    assert key_for(p) != key_for(p.model_copy(update={'sim': '2 SIM'}))

def test_case_normalization():
    p = ProductIn(brand='Apple', model='iPhone', category='Смартфоны', color='Black')
    assert key_for(p) == key_for(p.model_copy(update={'brand': 'apple', 'color': 'black'}))
