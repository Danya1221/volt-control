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
from app.integrated_collector import Base as CollectorBase, SupplierMessage, SupplierSource


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
            db.add(SupplierSource(account='miniapp-111', chat_id=12345678901, is_hi_catalog=False))
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
            db.add(miniapp.CatalogDestination(id=1,chat_id=-10099,title='Local',is_forum=True,can_manage_topics=True,checked_at=datetime.now(timezone.utc)))
            miniapp.save_topic(db,-10099,17,'Local topic',False)
            db.add(miniapp.CatalogTopicRule(chat_id=-10099,brand='Apple',category='Смартфоны',brand_key='apple',category_key='смартфоны',product_id=0,thread_id=17))
            db.commit()
            assert miniapp.topic_for_product(db,-10099,'Apple','Смартфоны').thread_id == 17
    finally:
        CollectorBase.metadata.drop_all(engine)
        main.Base.metadata.drop_all(engine)
        engine.dispose()



def test_reader_lock_blocks_parallel_use_and_releases(monkeypatch):
    import asyncio
    url = os.getenv('VOLT_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('No disposable PostgreSQL configured')
    parsed = make_url(url)
    if parsed.host not in ('127.0.0.1', 'localhost') or parsed.database != 'volt_control_test':
        pytest.fail('VOLT_TEST_POSTGRES_URL must target local disposable volt_control_test')
    engine = create_engine(url)
    monkeypatch.setattr(main, 'engine', engine)
    async def check():
        started = asyncio.Event()
        stop = asyncio.Event()
        calls = []
        async def monitor(config, db):
            calls.append(1)
            started.set()
            await stop.wait()
        monkeypatch.setattr(miniapp, 'monitor_account', monitor)
        account = {'telegram_id': '123456'}
        first = asyncio.create_task(miniapp.guarded_monitor(1, account, {}))
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(miniapp.ReaderBusy):
            await miniapp.guarded_monitor(1, account, {})
        assert len(calls) == 1
        stop.set()
        await first
        await miniapp.guarded_monitor(1, account, {})
        assert len(calls) == 2
    try:
        asyncio.run(check())
    finally:
        engine.dispose()
