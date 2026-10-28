import asyncio
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app import miniapp


def signed(user=123, age=0, token='bot-token'):
    data = {'auth_date': str(int(time.time()) - age), 'user': json.dumps({'id': user}), 'query_id': 'q'}
    check = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
    key = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    data['hash'] = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def test_init_data_rejects_tampering_expiry_and_non_owner():
    assert miniapp.verify_init_data(signed(), 'bot-token', 123)
    assert not miniapp.verify_init_data(signed(user=456), 'bot-token', 123)
    assert not miniapp.verify_init_data(signed(age=3601), 'bot-token', 123)
    assert not miniapp.verify_init_data(signed().replace('query_id=q', 'query_id=x'), 'bot-token', 123)
    assert not miniapp.verify_init_data(signed() + '&query_id=duplicate', 'bot-token', 123)


def test_owner_only_api_and_empty_accounts(monkeypatch):
    monkeypatch.setenv('VOLT_MINIAPP_ENABLED', '1')
    monkeypatch.setenv('TG_BOT_TOKEN', 'bot-token')
    monkeypatch.setenv('VOLT_OWNER_TG_ID', '123')
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    miniapp.Base.metadata.create_all(engine)
    monkeypatch.setattr(miniapp, 'Sessions', sessionmaker(engine))
    client = TestClient(app)
    assert client.get('/miniapp/api/accounts').status_code == 401
    assert client.get('/miniapp/api/accounts', headers={'X-Telegram-Init-Data': signed(user=456)}).status_code == 401
    response = client.get('/miniapp/api/accounts', headers={'X-Telegram-Init-Data': signed()})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert [a['connected'] for a in response.json()] == [False, False]
    engine.dispose()


def test_qr_login_saves_encrypted_session_and_recovers(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    miniapp.Base.metadata.create_all(engine)
    monkeypatch.setattr(miniapp, 'Sessions', sessionmaker(engine))
    monkeypatch.setenv('TG_API_ID', '12345')
    monkeypatch.setenv('TG_API_HASH', 'hash')
    key = Fernet.generate_key()
    monkeypatch.setenv('VOLT_SESSION_ENCRYPTION_KEY', key.decode())

    class QR:
        url = 'tg://login?token=fake'
        async def wait(self):
            await asyncio.sleep(0)
    class Session:
        def save(self): return 'secret-session'
    class User:
        id, first_name, bot = 456, 'Owner', False
    class Client:
        def __init__(self, *args): self.session = Session(); self.disconnected = False
        async def connect(self): pass
        async def disconnect(self): self.disconnected = True
        async def qr_login(self): return QR()
        async def get_me(self): return User()
    monkeypatch.setattr(miniapp, 'TelegramClient', Client)

    async def scenario():
        result = await miniapp.login(1)
        assert result['qr_image']
        await miniapp.attempts[1]['task']
        row = miniapp.saved(1)
        assert row['telegram_id'] == '456'
        assert row['session'] != 'secret-session'
        assert Fernet(key).decrypt(row['session'].encode()) == b'secret-session'
        assert miniapp.attempts[1]['state'] == 'connected'
        assert 'qr_image' not in miniapp.attempts[1]
        await miniapp.disconnect(1)
        assert miniapp.saved(1) is None
    asyncio.run(scenario())
    engine.dispose()


def test_qr_two_factor_and_same_account_rejection(monkeypatch):
    from telethon.errors import SessionPasswordNeededError
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    miniapp.Base.metadata.create_all(engine)
    monkeypatch.setattr(miniapp, 'Sessions', sessionmaker(engine))
    monkeypatch.setenv('TG_API_ID', '12345')
    monkeypatch.setenv('TG_API_HASH', 'hash')
    monkeypatch.setenv('VOLT_SESSION_ENCRYPTION_KEY', Fernet.generate_key().decode())

    class QR:
        url = 'tg://login?token=fake'
        async def wait(self): raise SessionPasswordNeededError(request=None)
    class Session:
        def save(self): return 'secret-session'
    class User:
        id, first_name, bot = 456, 'Owner', False
    class Client:
        def __init__(self, *args): self.session = Session()
        async def connect(self): pass
        async def disconnect(self): pass
        async def qr_login(self): return QR()
        async def sign_in(self, password): assert password == 'correct'
        async def get_me(self): return User()
    monkeypatch.setattr(miniapp, 'TelegramClient', Client)

    async def scenario():
        for slot in (1, 2):
            await miniapp.login(slot)
            await asyncio.sleep(0)
            assert miniapp.attempts[slot]['state'] == 'password_required'
            await miniapp.password(slot, miniapp.PasswordIn(password='correct'))
            await miniapp.attempts[slot]['task']
        assert miniapp.attempts[1]['state'] == 'connected'
        assert miniapp.attempts[2]['state'] == 'already_connected'
        assert miniapp.saved(2) is None
        await miniapp.disconnect(1)
        await miniapp.disconnect(2)
    asyncio.run(scenario())
    engine.dispose()


def test_message_inbox_is_owner_only_and_scoped_to_connected_account(monkeypatch):
    from datetime import datetime, timezone
    from app.integrated_collector import SupplierMessage, Base as CollectorBase
    monkeypatch.setenv('VOLT_MINIAPP_ENABLED', '1')
    monkeypatch.setenv('TG_BOT_TOKEN', 'bot-token')
    monkeypatch.setenv('VOLT_OWNER_TG_ID', '123')
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    miniapp.Base.metadata.create_all(engine)
    CollectorBase.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(miniapp, 'Sessions', sessions)
    with sessions() as db:
        db.add_all([
            miniapp.ReaderAccount(slot=1, telegram_id='111', display_name='Reader 1', encrypted_session='x', chats_json='[]'),
            miniapp.ReaderAccount(slot=2, telegram_id='222', display_name='Reader 2', encrypted_session='y', chats_json='[]'),
            SupplierMessage(account='miniapp-111', chat_id=99, message_id=1, text='iPhone 16 eSIM 60000', seen_at=datetime.now(timezone.utc)),
            SupplierMessage(account='miniapp-222', chat_id=99, message_id=2, text='Samsung Galaxy 2 SIM 70000', seen_at=datetime.now(timezone.utc)),
        ])
        db.commit()
    client = TestClient(app)
    assert client.get('/miniapp/api/accounts/1/messages').status_code == 401
    headers = {'X-Telegram-Init-Data': signed()}
    first = client.get('/miniapp/api/accounts/1/messages', headers=headers).json()
    second = client.get('/miniapp/api/accounts/2/messages', headers=headers).json()
    assert len(first['messages']) == len(second['messages']) == 1
    msg_id = first['messages'][0]['id']
    assert first['messages'][0]['text'] == 'iPhone 16 eSIM 60000'
    assert client.get(f'/miniapp/api/accounts/2/messages/{msg_id}/preview', headers=headers).status_code == 404
    preview = client.get(f'/miniapp/api/accounts/1/messages/{msg_id}/preview', headers=headers).json()
    assert preview['candidates'][0]['cost'] == '60000'
    assert preview['can_publish'] is False
    engine.dispose()



def test_reviewed_import_and_catalog_controls(monkeypatch):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.integrated_collector import SupplierMessage, Base as CollectorBase
    from app.main import Product, Supplier, Offer, Markup, today
    monkeypatch.setenv('VOLT_MINIAPP_ENABLED', '1')
    monkeypatch.setenv('TG_BOT_TOKEN', 'bot-token')
    monkeypatch.setenv('VOLT_OWNER_TG_ID', '123')
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    miniapp.Base.metadata.create_all(engine)
    CollectorBase.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(miniapp, 'Sessions', sessions)
    with sessions() as db:
        db.add(miniapp.ReaderAccount(slot=1, telegram_id='111', display_name='Reader', encrypted_session='x', chats_json='[]'))
        db.add(SupplierMessage(account='miniapp-111', chat_id=123, message_id=10,
                               text='iPhone 16 eSIM 60000', seen_at=datetime.now(timezone.utc)))
        db.commit()
        msg_id = db.scalar(select(SupplierMessage.id))
    client = TestClient(app)
    headers = {'X-Telegram-Init-Data': signed()}
    preview_url = f'/miniapp/api/accounts/1/messages/{msg_id}/preview'
    import_url = f'/miniapp/api/accounts/1/messages/{msg_id}/import-line'
    preview = client.get(preview_url, headers=headers).json()
    payload = {'line': 1, 'message_hash': preview['message_hash'], 'supplier_name': 'Supplier', 'confirmed_today': True}
    assert client.post(import_url, json=payload).status_code == 401
    assert client.post(import_url, json={**payload, 'confirmed_today': False}, headers=headers).status_code == 422
    assert client.post(import_url, json={**payload, 'message_hash': '0' * 64}, headers=headers).status_code == 409
    assert client.post(import_url, json={**payload, 'line': 2}, headers=headers).status_code == 422
    with sessions() as db:
        assert db.scalars(select(Product)).all() == []
        assert db.scalars(select(Supplier)).all() == []
    response = client.post(import_url, json=payload, headers=headers)
    assert response.status_code == 200
    product_id = response.json()['product_id']
    assert response.json()['approved'] is False
    with sessions() as db:
        offer = db.scalar(select(Offer))
        assert str(offer.cost) == '60000.00' and offer.confirmed_date == today()
        assert db.scalar(select(miniapp.OfferImport)).message_hash == preview['message_hash']
    assert client.get('/miniapp/api/products', headers=headers).json()[0]['status'] == 'hidden'
    assert client.put('/miniapp/api/markups', json={'scope': 'category', 'target': 'Смартфоны', 'amount': '5000'}, headers=headers).status_code == 200
    assert client.patch(f'/miniapp/api/products/{product_id}/approve', json={'value': True}, headers=headers).status_code == 200
    assert client.get('/miniapp/api/products', headers=headers).json()[0]['price'] == '65000.00'
    assert client.put('/miniapp/api/markups', json={'scope': 'sku', 'target': str(product_id), 'amount': '6000'}, headers=headers).status_code == 200
    assert client.get('/miniapp/api/products', headers=headers).json()[0]['price'] == '66000.00'
    assert client.patch(f'/miniapp/api/products/{product_id}/hide', json={'value': True}, headers=headers).status_code == 200
    assert client.get('/miniapp/api/products', headers=headers).json()[0]['status'] == 'hidden'
    with sessions() as db:
        row = db.get(SupplierMessage, msg_id)
        row.text = 'iPhone 16 eSIM 70000'
        db.commit()
    assert client.post(import_url, json=payload, headers=headers).status_code == 409
    with sessions() as db:
        assert str(db.scalar(select(Offer)).cost) == '60000.00'
        assert len(db.scalars(select(miniapp.OfferImport)).all()) == 1
    engine.dispose()



def test_group_binding_checks_access_and_never_publishes(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv('VOLT_MINIAPP_ENABLED', '1')
    monkeypatch.setenv('TG_BOT_TOKEN', 'bot-token')
    monkeypatch.setenv('VOLT_OWNER_TG_ID', '123')
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    miniapp.Base.metadata.create_all(engine)
    monkeypatch.setattr(miniapp, 'Sessions', sessionmaker(engine))

    class FakeBot:
        id = 999
        owner_admin = True
        bot_admin = True
        chat_type = 'supergroup'
        closed = 0
        def __init__(self, token): self.session = self
        async def close(self): FakeBot.closed += 1
        async def get_chat(self, target):
            return SimpleNamespace(id=-1001234567890, title='Catalog group', type=self.chat_type, is_forum=True)
        async def get_chat_member(self, chat_id, user_id):
            is_admin = self.bot_admin if user_id == self.id else self.owner_admin
            return SimpleNamespace(status='administrator' if is_admin else 'member', can_manage_topics=True)
    monkeypatch.setattr(miniapp, 'Bot', FakeBot)
    client = TestClient(app)
    headers = {'X-Telegram-Init-Data': signed()}
    path = '/miniapp/api/destination'
    assert client.get(path).status_code == 401
    assert client.put(path, json={'chat': '-1001234567890'}).status_code == 401
    assert client.get(path, headers=headers).json()['connected'] is False
    assert client.put(path, headers=headers, json={'chat': 'https://not-a-group'}).status_code == 422
    FakeBot.bot_admin = False
    assert client.put(path, headers=headers, json={'chat': '-1001234567890'}).status_code == 422
    assert client.get(path, headers=headers).json()['connected'] is False
    FakeBot.bot_admin = True
    response = client.put(path, headers=headers, json={'chat': '-1001234567890'})
    assert response.status_code == 200
    assert response.json()['chat_id'] == '-1001234567890'
    assert response.json()['is_forum'] is True
    assert response.json()['publication_enabled'] is False
    FakeBot.owner_admin = False
    assert client.put(path, headers=headers, json={'chat': '@another_group'}).status_code == 403
    assert client.get(path, headers=headers).json()['title'] == 'Catalog group'
    FakeBot.owner_admin = True
    FakeBot.chat_type = 'channel'
    assert client.put(path, headers=headers, json={'chat': '@another_group'}).status_code == 422
    assert FakeBot.closed == 4
    assert client.delete(path, headers=headers).json()['connected'] is False
    engine.dispose()
