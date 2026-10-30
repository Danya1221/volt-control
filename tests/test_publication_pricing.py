from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.main import Base, Markup, Offer, Product, Supplier
from app.miniapp import IncomingProduct, OfferImport
from app.integrated_collector import Base as CollectorBase, SupplierMessage
from app.pricing import NightReserve, Promotion
from app.publication_pricing import publication_price

TZ = ZoneInfo('Europe/Moscow')


def at(hour, minute=0, day=30):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


@pytest.fixture
def catalog():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    CollectorBase.metadata.create_all(engine)
    with Session(engine) as db:
        p = Product(sku_key='one', brand='Apple', model='iPhone 17', category='Смартфоны',
                    memory='256GB', color='Black', sim='eSIM', approved=True, hidden=False)
        db.add(p)
        db.add_all([Supplier(id=1, name='s1'), Supplier(id=2, name='s2')])
        db.add_all([Markup(scope='category', target='Смартфоны', amount=Decimal('1000')),
                    Promotion(scope='line', target='iPhone 17', amount=Decimal('300'), enabled=True),
                    NightReserve(category='Смартфоны', amount=Decimal('500'))])
        db.flush()
        yield db, p
    engine.dispose()


def offer_with_source(db, p, supplier, amount, source, reviewed=None):
    text = f'iPhone 17 256 eSIM supplier {supplier}: {amount}'
    digest = sha256(text.encode()).hexdigest()
    message = SupplierMessage(account=f'acct{supplier}', chat_id=100 + supplier,
                              message_id=10 + supplier, text=text,
                              seen_at=source.astimezone(timezone.utc))
    db.add(message)
    db.flush()
    offer = Offer(product_id=p.id, supplier_id=supplier, cost=Decimal(amount),
                  confirmed_date=source.date().isoformat(), active=True)
    db.add_all([offer, IncomingProduct(product_id=p.id, account=message.account,
        chat_id=message.chat_id, message_id=message.message_id, stored_message_id=message.id,
        line=1, message_hash=digest, source_price=Decimal(amount), source_at=source.astimezone(timezone.utc)),
        OfferImport(product_id=p.id, supplier_id=supplier, account=message.account,
        chat_id=message.chat_id, message_id=message.message_id, line=1,
        message_hash=digest, cost=Decimal(amount), imported_at=(reviewed or source).astimezone(timezone.utc))])
    db.flush()
    # Exercise database-loaded values (SQLite strips the UTC timezone marker).
    db.expire_all()
    return offer, message


def test_verified_minimum_markup_and_promotion(catalog):
    db, p = catalog
    offer_with_source(db, p, 1, '10000', at(11))
    offer_with_source(db, p, 2, '9000', at(12))
    result = publication_price(db, p, at(13))
    assert result['status'] == 'priced'
    assert Decimal(result['price']) == Decimal('9700')
    assert Decimal(result['base_price']) == Decimal('10000')


def test_night_reserve_and_fresh_after_20(catalog):
    db, p = catalog
    offer_with_source(db, p, 1, '10000', at(11))
    result = publication_price(db, p, at(20, 10))
    assert Decimal(result['price']) == Decimal('11500')
    assert Decimal(result['discount']) == 0
    offer_with_source(db, p, 2, '9000', at(20, 15))
    result = publication_price(db, p, at(21))
    assert Decimal(result['price']) == Decimal('10000')
    assert Decimal(result['reserve']) == 0


def test_reviewing_a_pre_10_source_does_not_make_it_fresh(catalog):
    db, p = catalog
    offer_with_source(db, p, 1, '10000', at(9), reviewed=at(11))
    assert publication_price(db, p, at(12))['price'] == 'По запросу'


def test_unverified_same_day_competing_offer_blocks_numeric_price(catalog):
    db, p = catalog
    offer_with_source(db, p, 1, '10000', at(11))
    db.add(Offer(product_id=p.id, supplier_id=2, cost=Decimal('8000'),
                 confirmed_date='2026-10-30', active=True))
    db.flush()
    assert publication_price(db, p, at(13))['price'] == 'По запросу'


def test_source_edited_or_missing_blocks_numeric_price(catalog):
    db, p = catalog
    _, message = offer_with_source(db, p, 1, '10000', at(11))
    message.text = 'прайс изменён'
    db.flush()
    assert publication_price(db, p, at(12))['price'] == 'По запросу'


def test_previous_day_and_before_opening_never_carry_numeric_price(catalog):
    db, p = catalog
    offer_with_source(db, p, 1, '10000', at(21, day=29))
    assert publication_price(db, p, at(9))['price'] == 'По запросу'
    assert publication_price(db, p, at(11))['price'] == 'По запросу'


def test_invalid_source_future_and_hidden_product_are_not_priced(catalog):
    db, p = catalog
    offer_with_source(db, p, 1, '10000', at(13))
    assert publication_price(db, p, at(12))['price'] == 'По запросу'
    p.hidden = True
    assert publication_price(db, p, at(14))['price'] == 'По запросу'
