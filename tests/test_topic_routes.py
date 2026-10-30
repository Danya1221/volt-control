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
        assert 'не привязанный' in wrong.answer.await_args.args[0]
        checked.assert_not_awaited()
        good=msg(123,-10099)
        await admin_bot.register_topic_command(good,123)
        assert 'добавлена' in good.answer.await_args.args[0]
        checked.assert_awaited_once()
    asyncio.run(scenario())
    with db() as session:
        topic=session.scalar(select(miniapp.CatalogTopic).where(miniapp.CatalogTopic.thread_id==34))
        assert topic.title == 'Наушники' and topic.chat_id == -10099
    engine.dispose()


def test_sync_uses_existing_reader_session_and_never_creates_new_client(monkeypatch):
    engine, db = setup_db(monkeypatch)
    class Reader:
        def is_connected(self): return True
        async def get_dialogs(self): pass
        async def get_input_entity(self, chat_id):
            assert chat_id == -10099
            return 'forum-peer'
        async def __call__(self, req):
            assert req.peer == 'forum-peer'
            return SimpleNamespace(count=1, topics=[SimpleNamespace(id=77,title='Смартфоны',closed=False)])
    miniapp.worker_clients[1] = Reader()
    try:
        result=asyncio.run(miniapp.sync_catalog_topics())
        assert result['loaded_count'] == 1 and not result['incomplete']
        assert any(t['thread_id']==77 and t['title']=='Смартфоны' for t in result['topics'])
    finally:
        miniapp.worker_clients.clear()
        engine.dispose()


def test_owner_can_join_reader_without_exposing_invite(monkeypatch):
    from telethon.tl.functions.messages import ImportChatInviteRequest
    engine, db = setup_db(monkeypatch)
    with db() as session:
        session.add(miniapp.ReaderAccount(slot=1, telegram_id='678', display_name='Reader', encrypted_session='x', chats_json='[]'))
        session.commit()
    calls = []
    bots = []
    class Reader:
        def is_connected(self): return True
        async def __call__(self, req):
            assert isinstance(req, ImportChatInviteRequest)
            calls.append('join')
    class BotStub:
        def __init__(self, token):
            self.session = SimpleNamespace(close=AsyncMock())
            self.get_chat_member = AsyncMock(return_value=SimpleNamespace(status='left'))
            self.create_chat_invite_link = AsyncMock(return_value=SimpleNamespace(invite_link='https://t.me/+SafeLocalInvite123'))
            self.revoke_chat_invite_link = AsyncMock()
            bots.append(self)
    miniapp.worker_clients[1] = Reader()
    monkeypatch.setattr(miniapp, 'Bot', BotStub)
    check = AsyncMock(return_value={'is_forum': True})
    monkeypatch.setattr(miniapp, 'verify_destination', check)
    client = TestClient(app)
    headers = {'X-Telegram-Init-Data': signed()}
    try:
        assert client.post('/miniapp/api/destination/topics/join/1').status_code == 401
        assert not bots and not calls
        response = client.post('/miniapp/api/destination/topics/join/1', headers=headers)
        assert response.status_code == 200 and response.json() == {'ok': True, 'already_member': False}
        assert 'SafeLocalInvite123' not in response.text
        assert calls == ['join']
        bots[0].create_chat_invite_link.assert_awaited_once()
        assert bots[0].create_chat_invite_link.await_args.kwargs['member_limit'] == 1
        bots[0].revoke_chat_invite_link.assert_awaited_once()
        bots[0].session.close.assert_awaited_once()
        check.assert_awaited_once()
    finally:
        miniapp.worker_clients.clear()
        engine.dispose()


def test_already_joined_and_invite_permission_failure(monkeypatch):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import GetMe
    engine, db = setup_db(monkeypatch)
    with db() as session:
        session.add(miniapp.ReaderAccount(slot=1, telegram_id='678', display_name='Reader', encrypted_session='x', chats_json='[]'))
        session.commit()
    class Reader:
        def is_connected(self): return True
        async def __call__(self, req): raise AssertionError('must not join')
    miniapp.worker_clients[1] = Reader()
    bots = []
    class BotStub:
        status = 'member'
        def __init__(self, token):
            self.session = SimpleNamespace(close=AsyncMock())
            self.get_chat_member = AsyncMock(return_value=SimpleNamespace(status=BotStub.status))
            self.create_chat_invite_link = AsyncMock(side_effect=TelegramBadRequest(method=GetMe(), message='not allowed'))
            self.revoke_chat_invite_link = AsyncMock()
            bots.append(self)
    monkeypatch.setattr(miniapp, 'Bot', BotStub)
    monkeypatch.setattr(miniapp, 'verify_destination', AsyncMock(return_value={'is_forum': True}))
    client = TestClient(app)
    headers = {'X-Telegram-Init-Data': signed()}
    try:
        result = client.post('/miniapp/api/destination/topics/join/1', headers=headers)
        assert result.json() == {'ok': True, 'already_member': True}
        bots[-1].create_chat_invite_link.assert_not_awaited()
        BotStub.status = 'left'
        result = client.post('/miniapp/api/destination/topics/join/1', headers=headers)
        assert result.status_code == 422 and 'Приглашение пользователей' in result.json()['detail']
        bots[-1].session.close.assert_awaited_once()
    finally:
        miniapp.worker_clients.clear()
        engine.dispose()


def test_topic_sync_explains_safe_error_without_exception_details(monkeypatch):
    engine, db = setup_db(monkeypatch)
    class Reader:
        def is_connected(self): return True
        async def get_input_entity(self, chat_id): raise ValueError('sensitive value')
        async def get_dialogs(self): pass
    miniapp.worker_clients[1] = Reader()
    try:
        client = TestClient(app)
        headers = {'X-Telegram-Init-Data': signed()}
        result = client.post('/miniapp/api/destination/topics/sync', headers=headers)
        assert result.status_code == 422
        assert 'Аккаунт 1' in result.json()['detail'] and 'ValueError' in result.json()['detail']
        assert 'sensitive' not in result.text
    finally:
        miniapp.worker_clients.clear()
        engine.dispose()
