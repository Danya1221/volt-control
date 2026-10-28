"""Run only against an explicitly designated, disposable local PostgreSQL database."""
import hashlib
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import app.main as main
from app import miniapp
from app.integrated_collector import Base as CollectorBase, SupplierMessage


def test_import_on_disposable_postgres(monkeypatch):
    url = os.getenv('VOLT_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('No disposable PostgreSQL configured')
    parsed = make_url(url)
    if parsed.host not in ('127.0.0.1', 'localhost') or parsed.database != 'volt_control_test':
        pytest.fail('VOLT_TEST_POSTGRES_URL must target local disposable volt_control_test')
    engine = create_engine(url)
    main.Base.metadata.create_all(engine)
    CollectorBase.metadata.create_all(engine)
    db_factory = sessionmaker(engine)
    monkeypatch.setattr(miniapp, 'Sessions', db_factory)
    try:
        with db_factory() as db:
            db.add(miniapp.ReaderAccount(slot=1, telegram_id='111', display_name='Test', encrypted_session='unused', chats_json='[]'))
            db.add(SupplierMessage(account='miniapp-111', chat_id=12345678901, message_id=50,
                                   text='iPhone 16 eSIM 60000', seen_at=datetime.now(timezone.utc)))
            db.commit()
            message_id = db.scalar(select(SupplierMessage.id))
        content_hash = hashlib.sha256(b'iPhone 16 eSIM 60000').hexdigest()
        result = miniapp.import_line(1, message_id, miniapp.ImportLineIn(
            line=1, message_hash=content_hash, supplier_name='Local test supplier', confirmed_today=True))
        assert result['approved'] is False
        with db_factory() as db:
            assert db.get(main.Product, result['product_id']).approved is False
            audit = db.scalar(select(miniapp.OfferImport))
            assert audit.chat_id == 12345678901
            assert audit.message_hash == content_hash
    finally:
        CollectorBase.metadata.drop_all(engine)
        main.Base.metadata.drop_all(engine)
        engine.dispose()
