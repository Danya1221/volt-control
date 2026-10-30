import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import miniapp, admin_bot
from app.main import app, Product
from tests.test_miniapp import signed


def setup_db(monkeypatch):
    monkeypatch.setenv('VOLT_MINIAPP_ENABLED', '1')
    monkeypatch.setenv('TG_BOT_TOKEN', 'bot-token')
    monkeypatch.setenv('VOLT_OWNER_TG_ID', '123')
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    miniapp.Base.metadata.create_all(engine)
    db_factory = sessionmaker(engine)
    monkeypatch.setattr(miniapp, 'Sessions', db_factory)
    with db_factory() as db:
        db.add(miniapp.CatalogDestination(id=1, chat_id=-10099, title='Group', is_forum=True,
                                         can_manage_topics=True, checked_at=datetime.now(timezone.utc)))
        db.add(Product(id=9, sku_key='local-product', brand='Apple', model='iPhone', category='Смартфоны', memory='', color='', sim='eSIM', approved=False, hidden=False))
        for thread_id, title in [(10, 'Общее'), (11, 'Apple'), (12, 'iPhone')]:
            miniapp.save_topic(db, -10099, thread_id, title, False)
        db.commit()
    return engine, db_factory


def test_topic_rules_are_owner_only_and_scoped_to_bound_chat(monkeypatch):
    engine, db = setup_db(monkeypatch)
    client = TestClient(app)
    headers = {'X-Telegram-Init-Data': signed()}
    assert client.get('/miniapp/api/destination/topics').status_code == 401
    assert client.put('/miniapp/api/destination/routes', json={'brand':'Apple','thread_id':10}).status_code == 401
    for payload in [dict(category='Смартфоны',thread_id=10), dict(brand='Apple',thread_id=11),
                    dict(brand='Apple',category='Смартфоны',thread_id=12), dict(product_id=9,thread_id=10)]:
        assert client.put('/miniapp/api/destination/routes', headers=headers, json=payload).status_code == 200
    assert client.put('/miniapp/api/destination/routes', headers=headers, json={'thread_id':10}).status_code == 422
    assert client.put('/miniapp/api/destination/routes', headers=headers, json={'product_id':9,'brand':'Apple','thread_id':10}).status_code == 422
    assert client.put('/miniapp/api/destination/routes', headers=headers, json={'product_id':999,'thread_id':10}).status_code == 404
    assert client.put('/miniapp/api/destination/routes', headers=headers, json={'brand':'Apple','thread_id':999}).status_code == 422
    with db() as session:
        assert miniapp.topic_for_product(session,-10099,'apple','смартфоны',product_id=9).thread_id == 10
        assert miniapp.topic_for_product(session,-10099,'apple','смартфоны').thread_id == 12
        assert miniapp.topic_for_product(session,-10099,'Apple','Наушники').thread_id == 11
        assert miniapp.topic_for_product(session,-10099,'Samsung','Смартфоны').thread_id == 10
        assert miniapp.topic_for_product(session,-10099,'Samsung','Наушники') is None
        assert miniapp.topic_for_product(session,-10098,'Apple','Смартфоны') is None
        topic = session.scalar(select(miniapp.CatalogTopic).where(miniapp.CatalogTopic.thread_id == 12))
        topic.closed = True
        session.commit()
        assert miniapp.topic_for_product(session,-10099,'Apple','Смартфоны') is None
    topics = client.get('/miniapp/api/destination/topics', headers=headers).json()
    assert len(topics['rules']) == 4 and topics['publication_enabled'] is False
    with db() as session:
        session.get(miniapp.CatalogDestination,1).chat_id = -10098
        session.commit()
    assert client.get('/miniapp/api/destination/topics', headers=headers).json()['rules'] == []
    assert client.delete('/miniapp/api/destination/routes/1', headers=headers).status_code == 404
    engine.dispose()


def test_topic_command_checks_owner_chat_and_rights(monkeypatch):
    engine, db = setup_db(monkeypatch)
    checked = AsyncMock(return_value={'is_forum':True})
    monkeypatch.setattr(miniapp, 'verify_destination', checked)
    def msg(uid, chat, name='Наушники'):
        return SimpleNamespace(from_user=SimpleNamespace(id=uid),sender_chat=None,
                               chat=SimpleNamespace(type='supergroup', id=chat, is_forum=True),
                               message_thread_id=34,text='/volttopic '+name,answer=AsyncMock(),bot=object())
    async def scenario():
        other=msg(456,-10099)
        await admin_bot.register_topic_command(other,123)
        other.answer.assert_not_awaited()
        wrong=msg(123,-10098)
        await admin_bot.register_topic_command(wrong,123)
        wrong.answer.assert_not_awaited()
        checked.assert_not_awaited()
        good=msg(123,-10099)
        await admin_bot.register_topic_command(good,123)
        good.answer.assert_not_awaited()
        checked.assert_awaited_once()
    asyncio.run(scenario())
    with db() as session:
        topic=session.scalar(select(miniapp.CatalogTopic).where(miniapp.CatalogTopic.thread_id==34))
        assert topic.title == 'Наушники' and topic.chat_id == -10099
    engine.dispose()


def test_sync_returns_observed_topics_without_user_account(monkeypatch):
    engine, db = setup_db(monkeypatch)
    class ForbiddenReader:
        def is_connected(self):
            raise AssertionError('reader session must not be used')
    miniapp.worker_clients[1] = ForbiddenReader()
    try:
        result = asyncio.run(miniapp.sync_catalog_topics())
        assert result['loaded_count'] == 3 and result['incomplete']
        assert {x['title'] for x in result['topics']} == {'Общее', 'Apple', 'iPhone'}
        client = TestClient(app)
        assert client.post('/miniapp/api/destination/topics/join/1').status_code == 401
        assert client.post('/miniapp/api/destination/topics/join/1', headers={'X-Telegram-Init-Data': signed()}).status_code == 410
    finally:
        miniapp.worker_clients.clear()
        engine.dispose()


def test_observe_topics_tracks_real_events_and_never_changes_other_groups(monkeypatch):
    engine, db = setup_db(monkeypatch)
    def message(**values):
        defaults = dict(chat=SimpleNamespace(type='supergroup', id=-10099, is_forum=True),
                        message_id=90, message_thread_id=77)
        return SimpleNamespace(**(defaults | values))
    async def run():
        await miniapp.observe_catalog_topic(message())
        await miniapp.observe_catalog_topic(message(forum_topic_created=SimpleNamespace(name='Камеры')))
        await miniapp.observe_catalog_topic(message(forum_topic_edited=SimpleNamespace(name='Аксессуары')))
        await miniapp.observe_catalog_topic(message(forum_topic_closed=SimpleNamespace()))
        await miniapp.observe_catalog_topic(message())  # must not reopen or rename
        await miniapp.observe_catalog_topic(message(chat=SimpleNamespace(type='supergroup', id=-10098, is_forum=True),
                                                    forum_topic_edited=SimpleNamespace(name='Чужая')))
    asyncio.run(run())
    with db() as session:
        topic = session.scalar(select(miniapp.CatalogTopic).where(miniapp.CatalogTopic.thread_id == 77))
        assert (topic.chat_id, topic.title, topic.closed) == (-10099, 'Аксессуары', True)
    asyncio.run(miniapp.observe_catalog_topic(message(forum_topic_reopened=SimpleNamespace())))
    with db() as session:
        topic = session.scalar(select(miniapp.CatalogTopic).where(miniapp.CatalogTopic.thread_id == 77))
        assert (topic.title, topic.closed) == ('Аксессуары', False)
    engine.dispose()


def test_observe_unknown_and_general_events_keep_status_unknown(monkeypatch):
    engine, db = setup_db(monkeypatch)
    chat = SimpleNamespace(type='supergroup', id=-10099, is_forum=True)
    asyncio.run(miniapp.observe_catalog_topic(SimpleNamespace(chat=chat, message_thread_id=78)))
    asyncio.run(miniapp.observe_catalog_topic(SimpleNamespace(chat=chat, message_thread_id=None, general_forum_topic_hidden=SimpleNamespace())))
    with db() as session:
        topics = {t.thread_id: t for t in session.scalars(select(miniapp.CatalogTopic)).all()}
        assert (topics[78].title, topics[78].closed) == ('Тема 78', None)
        assert (topics[1].title, topics[1].closed) == ('Тема 1', None)
    engine.dispose()


def test_topic_middleware_observes_before_other_handlers_and_never_sends(monkeypatch):
    setup_db(monkeypatch)
    observed = AsyncMock()
    handler = AsyncMock(return_value='handled')
    monkeypatch.setattr(miniapp, 'observe_catalog_topic', observed)
    dispatcher = admin_bot.create_dispatcher(123)
    event = SimpleNamespace(forward_origin=object(), text='/start')
    middleware = list(dispatcher.message.outer_middleware)[-1]
    result = asyncio.run(middleware(handler, event, {}))
    assert result == 'handled'
    observed.assert_awaited_once_with(event)
    handler.assert_awaited_once_with(event, {})


def test_manual_name_preserves_existing_closed_state(monkeypatch):
    engine, db = setup_db(monkeypatch)
    monkeypatch.setattr(miniapp, 'verify_destination', AsyncMock(return_value={'is_forum':True}))
    with db() as session:
        topic = session.scalar(select(miniapp.CatalogTopic).where(miniapp.CatalogTopic.thread_id == 10))
        topic.closed = True
        session.commit()
    asyncio.run(miniapp.register_catalog_topic(-10099, 10, 'Новое имя', object()))
    with db() as session:
        topic = session.scalar(select(miniapp.CatalogTopic).where(miniapp.CatalogTopic.thread_id == 10))
        assert (topic.title, topic.closed) == ('Новое имя', True)
    engine.dispose()
