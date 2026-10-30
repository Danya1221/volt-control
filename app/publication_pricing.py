"""Conservative retail prices, supported by a reviewed Telegram source.

An offer's date is not evidence that its source was refreshed after 10:00.
This module never substitutes collection or import time for source time.
"""
from datetime import datetime, time, timezone
from decimal import Decimal
import hashlib
import hmac
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.main import Markup, Offer
from app.miniapp import IncomingProduct, OfferImport
from app.integrated_collector import SupplierMessage
from app.pricing import NightReserve, Promotion, model_in_line

MOSCOW = ZoneInfo('Europe/Moscow')


def _utc(value):
    # SQLite drops timezone information from UTC values; PostgreSQL preserves it.
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _source_time(db, offer, now):
    """Return source datetime only when current offer has verifiable provenance."""
    imported = db.scalar(select(OfferImport).where(
        OfferImport.product_id == offer.product_id,
        OfferImport.supplier_id == offer.supplier_id,
    ).order_by(OfferImport.imported_at.desc(), OfferImport.id.desc()).limit(1))
    if imported is None or imported.cost != offer.cost:
        return None
    source = db.scalar(select(IncomingProduct).where(
        IncomingProduct.product_id == offer.product_id,
        IncomingProduct.account == imported.account,
        IncomingProduct.chat_id == imported.chat_id,
        IncomingProduct.message_id == imported.message_id,
        IncomingProduct.line == imported.line,
        IncomingProduct.message_hash == imported.message_hash,
    ).limit(1))
    if source is None or source.source_price != offer.cost:
        return None
    message = db.get(SupplierMessage, source.stored_message_id)
    if (message is None or message.account != imported.account or
            message.chat_id != imported.chat_id or message.message_id != imported.message_id):
        return None
    digest = hashlib.sha256((message.text or '').encode('utf-8')).hexdigest()
    if not hmac.compare_digest(digest, imported.message_hash):
        return None
    source_at, reviewed_at = _utc(source.source_at), _utc(imported.imported_at)
    if not source_at or not reviewed_at or source_at > reviewed_at or reviewed_at > now:
        return None
    local_source, local_reviewed = source_at.astimezone(MOSCOW), reviewed_at.astimezone(MOSCOW)
    if local_source.date() != local_reviewed.date() or local_reviewed.date() != now.astimezone(MOSCOW).date():
        return None
    return local_source


def _markup(db, product):
    rules = db.scalars(select(Markup)).all()
    for scope, target in (('sku', str(product.id)), ('model', product.model)):
        match = next((r for r in rules if r.scope == scope and r.target.casefold() == target.casefold()), None)
        if match:
            return match.amount
    lines = sorted((r for r in rules if r.scope == 'line' and model_in_line(product.model, r.target)),
                   key=lambda r: len(r.target), reverse=True)
    if lines:
        return lines[0].amount
    category = next((r for r in rules if r.scope == 'category' and r.target.casefold() == product.category.casefold()), None)
    return category.amount if category else Decimal('0')


def publication_price(db, product, now=None):
    """Price one exact persisted product, or return 'По запросу' if uncertain.

    This does not establish that different Product records are identical across
    suppliers; that remains a separate, admin-confirmed SKU mapping problem.
    """
    now = _utc(now or datetime.now(timezone.utc))
    local_now = now.astimezone(MOSCOW)
    result = {'status': 'on_request', 'price': 'По запросу', 'base_price': None,
              'discount': '0', 'reserve': '0', 'markup': '0'}
    if not product.approved or product.hidden or local_now.hour < 10:
        return result
    offers = db.scalars(select(Offer).where(Offer.product_id == product.id,
        Offer.active.is_(True), Offer.confirmed_date == local_now.date().isoformat())).all()
    current = []
    for offer in offers:
        source_at = _source_time(db, offer, now)
        # An unverified competing offer might be the cheaper current offer.
        if source_at is None:
            return result
        if source_at.time().replace(tzinfo=None) >= time(10):
            current.append((offer, source_at))
    if not current:
        return result
    cost = min(offer.cost for offer, _ in current)
    markup = _markup(db, product)
    base = cost + markup
    night = local_now.hour >= 20
    reserve = Decimal('0')
    discount = Decimal('0')
    if night and not any(source.hour >= 20 for _, source in current):
        rule = db.get(NightReserve, product.category)
        reserve = rule.amount if rule else Decimal('0')
    elif not night:
        promos = db.scalars(select(Promotion).where(Promotion.enabled.is_(True))).all()
        eligible = [r for r in promos if (r.ends_at is None or (_utc(r.ends_at) and _utc(r.ends_at) > now))
                    and ((r.scope == 'sku' and r.target == str(product.id))
                         or (r.scope == 'line' and model_in_line(product.model, r.target)))]
        eligible.sort(key=lambda r: (r.scope == 'sku', len(r.target)), reverse=True)
        if eligible:
            discount = min(eligible[0].amount, markup)
    result.update(status='priced', price=str(base + reserve - discount), base_price=str(base),
                  cost=str(cost), discount=str(discount), reserve=str(reserve), markup=str(markup))
    return result
