import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

from app import integrated_collector as collector, miniapp


def test_inaccessible_chat_does_not_stop_other_chat(monkeypatch):
    class FakeClient:
        def __init__(self, *args):
            self.disconnected = asyncio.get_running_loop().create_future()
            self.disconnected.set_result(None)
            self.handlers = []
        async def connect(self): pass
        async def disconnect(self): pass
        async def is_user_authorized(self): return True
        async def get_entity(self, chat):
            if chat == '@missing':
                raise ValueError('private details must not be exposed')
            return chat
        async def get_peer_id(self, entity): return 123
        def on(self, event):
            def register(fn):
                self.handlers.append(fn)
                return fn
            return register
        async def iter_messages(self, entity, **kwargs):
            if False:
                yield None
    @contextmanager
    def db():
        yield SimpleNamespace(scalar=lambda query: None)
    monkeypatch.setattr(collector, 'TelegramClient', FakeClient)
    checked, ready = [], []
    asyncio.run(collector.monitor_account({'name':'account', 'session_string':'', 'api_id':1,
        'api_hash':'x', 'chats':['@missing', '@working'],
        'on_chats':checked.append, 'on_ready':lambda: ready.append(True)}, db))
    assert checked == [['@missing']]
    assert ready == [True]


def test_reader_exposes_safe_error_category(monkeypatch):
    async def fail(config, db):
        raise ValueError('sensitive details')
    async def cancel(delay):
        raise asyncio.CancelledError()
    monkeypatch.setattr(miniapp, 'saved', lambda slot: {'telegram_id':'1','chats':['@x'],'session':'x'})
    monkeypatch.setattr(miniapp, 'settings', lambda: (1, 'x', SimpleNamespace(decrypt=lambda _: b'session')))
    monkeypatch.setattr(miniapp, 'monitor_account', fail)
    monkeypatch.setattr(miniapp.asyncio, 'sleep', cancel)
    try:
        asyncio.run(miniapp.reader_worker(1))
    except asyncio.CancelledError:
        pass
    assert miniapp.worker_states[1] == 'retrying'
    assert miniapp.worker_details[1]['reason'] == 'unknown'
    assert 'sensitive' not in repr(miniapp.worker_details[1])
    miniapp.worker_states.clear()
    miniapp.worker_details.clear()
