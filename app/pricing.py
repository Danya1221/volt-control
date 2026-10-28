"""Pricing rules for VOLT Control; no automatic publication or demo records."""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import Integer, String, Numeric, DateTime, Boolean, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from app.main import Base, Sessions, Product, Offer, Markup
from app.miniapp import owner

MOSCOW = ZoneInfo("Europe/Moscow")
router = APIRouter(prefix="/miniapp/api/pricing", dependencies=[Depends(owner)])

class NightReserve(Base):
    __tablename__ = "night_reserves"
    category: Mapped[str] = mapped_column(String(100), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14,2))

class Promotion(Base):
    __tablename__ = "promotions"
    __table_args__ = (UniqueConstraint("scope", "target"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(20))
    target: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(14,2))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class Money(BaseModel):
    amount: Decimal = Field(ge=0, le=Decimal("999999999999.99"), max_digits=14, decimal_places=2)

class PromoIn(Money):
    scope: str
    target: str = Field(min_length=1, max_length=200)
    ends_at: datetime | None = None
    enabled: bool = True

def model_in_line(model: str, line: str) -> bool:
    """Explicit prefix with a word boundary; not a fuzzy substring."""
    a, b = model.casefold().strip(), line.casefold().strip()
    return bool(b) and (a == b or a.startswith(b + " "))

def pricing_for(db, p, now=None):
    now = now or datetime.now(MOSCOW)
    day = now.date().isoformat()
    active = db.scalars(select(Offer).where(
        Offer.product_id == p.id, Offer.active.is_(True),
        Offer.confirmed_date == day)).all()
    night = not (10 <= now.hour < 20)
    result = {"id": p.id, "mode": "night" if night else "day",
              "status": "hidden" if p.hidden or not p.approved else "on_request",
              "price": "По запросу", "base_price": None, "discount": "0.00",
              "reserve": "0.00", "markup": "0.00"}
    if p.hidden or not p.approved or not active:
        return result
    cost = min(o.cost for o in active)
    rules = db.scalars(select(Markup)).all()
    markup = Decimal("0")
    for scope, target in (("sku", str(p.id)), ("model", p.model)):
        match = next((r for r in rules if r.scope == scope and r.target.casefold() == target.casefold()), None)
        if match:
            markup = match.amount
            break
    else:
        lines = sorted((r for r in rules if r.scope == "line" and model_in_line(p.model, r.target)),
                       key=lambda r: len(r.target), reverse=True)
        if lines:
            markup = lines[0].amount
        else:
            category = next((r for r in rules if r.scope == "category" and r.target.casefold() == p.category.casefold()), None)
            if category:
                markup = category.amount
    base = cost + markup
    reserve = Decimal("0")
    if night:
        reserve_rule = db.get(NightReserve, p.category)
        if reserve_rule:
            reserve = reserve_rule.amount
    discount = Decimal("0")
    if not night:
        promos = db.scalars(select(Promotion).where(Promotion.enabled.is_(True))).all()
        eligible = [r for r in promos if (r.ends_at is None or r.ends_at > now)
                    and ((r.scope == "sku" and r.target == str(p.id))
                         or (r.scope == "line" and model_in_line(p.model, r.target)))]
        eligible.sort(key=lambda r: (r.scope == "sku", len(r.target)), reverse=True)
        if eligible:
            discount = min(eligible[0].amount, markup)
    result.update(status="priced", price=str(base + reserve - discount),
                  base_price=str(base), cost=str(cost), markup=str(markup),
                  reserve=str(reserve), discount=str(discount))
    return result

@router.get("/overview")
def overview():
    now = datetime.now(MOSCOW)
    with Sessions() as db:
        products = db.scalars(select(Product).order_by(Product.brand, Product.model)).all()
        items = [{**{"brand": p.brand, "model": p.model, "category": p.category,
                     "approved": p.approved, "hidden": p.hidden},
                  **pricing_for(db, p, now)} for p in products]
        return {"mode": "day" if 10 <= now.hour < 20 else "night",
                "moscow_time": now.isoformat(), "total": len(items),
                "priced": sum(x["status"] == "priced" for x in items),
                "review": sum(not x["approved"] for x in items),
                "items": items}

@router.get("/rules")
def rules():
    with Sessions() as db:
        return {
            "markups": [{"scope": r.scope, "target": r.target, "amount": str(r.amount)}
                        for r in db.scalars(select(Markup).order_by(Markup.scope, Markup.target))],
            "reserves": [{"category": r.category, "amount": str(r.amount)}
                         for r in db.scalars(select(NightReserve).order_by(NightReserve.category))],
            "promotions": [{"scope": r.scope, "target": r.target, "amount": str(r.amount),
                            "enabled": r.enabled, "ends_at": r.ends_at.isoformat() if r.ends_at else None}
                           for r in db.scalars(select(Promotion).order_by(Promotion.scope, Promotion.target))]
        }

@router.put("/reserve/{category}")
def set_reserve(category: str, body: Money):
    if not category.strip() or len(category) > 100:
        raise HTTPException(422, "Некорректная категория")
    with Sessions() as db:
        obj = db.get(NightReserve, category)
        if obj is None:
            obj = NightReserve(category=category, amount=body.amount)
            db.add(obj)
        else:
            obj.amount = body.amount
        db.commit()
    return {"ok": True}

@router.put("/promotion")
def set_promotion(body: PromoIn):
    if body.scope not in ("sku", "line") or body.target != body.target.strip():
        raise HTTPException(422, "Акция допускается для SKU или линейки")
    if body.scope == "sku" and not body.target.isdigit():
        raise HTTPException(422, "Для SKU нужен числовой ID")
    if body.ends_at and (body.ends_at.tzinfo is None or body.ends_at.utcoffset() is None):
        raise HTTPException(422, "Дата окончания должна содержать часовой пояс")
    with Sessions() as db:
        if body.scope == "sku" and db.get(Product, int(body.target)) is None:
            raise HTTPException(404, "Товар не найден")
        obj = db.scalar(select(Promotion).where(Promotion.scope == body.scope, Promotion.target == body.target))
        if obj is None:
            obj = Promotion(scope=body.scope, target=body.target)
            db.add(obj)
        obj.amount, obj.ends_at, obj.enabled = body.amount, body.ends_at, body.enabled
        db.commit()
    return {"ok": True}
