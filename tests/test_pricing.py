"""Pricing regression checks with an isolated in-memory database."""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.main import Base, Product, Offer, Markup
from app.pricing import NightReserve, Promotion, pricing_for

TZ = ZoneInfo("Europe/Moscow")

def test_pricing_hierarchy_and_discount_cap():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        p = Product(sku_key="test", brand="Brand", model="Phone 17 Pro", category="phones",
                    memory="", color="", sim="", approved=True, hidden=False)
        db.add(p)
        db.flush()
        db.add(Offer(supplier_id=1, product_id=p.id, cost=Decimal("10000"),
                     confirmed_date="2026-10-28", active=True))
        db.add_all([
            Markup(scope="category", target="phones", amount=Decimal("1000")),
            Markup(scope="line", target="Phone 17", amount=Decimal("2000")),
            Markup(scope="model", target="Phone 17 Pro", amount=Decimal("3000")),
            Promotion(scope="sku", target=str(p.id), amount=Decimal("9999"), enabled=True),
            NightReserve(category="phones", amount=Decimal("500")),
        ])
        db.flush()
        day = pricing_for(db, p, datetime(2026, 10, 28, 14, tzinfo=TZ))
        assert Decimal(day["markup"]) == Decimal("3000")
        assert Decimal(day["price"]) == Decimal("10000")
        night = pricing_for(db, p, datetime(2026, 10, 28, 21, tzinfo=TZ))
        assert Decimal(night["price"]) == Decimal("13500")
        assert Decimal(night["discount"]) == Decimal("0")
        stale = pricing_for(db, p, datetime(2026, 10, 29, 11, tzinfo=TZ))
        assert stale["status"] == "on_request"
        assert stale["price"] == "По запросу"
    engine.dispose()

