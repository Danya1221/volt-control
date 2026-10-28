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
