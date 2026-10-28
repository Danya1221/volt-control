"""Owner-only Mini App and QR login for up to two Telegram reader accounts."""
import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import time
from contextlib import suppress
from urllib.parse import parse_qsl

import qrcode
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PasswordHashInvalidError
from telethon.sessions import StringSession

from app.main import Base, Sessions
from app.integrated_collector import Base as CollectorBase, SupplierMessage, monitor_account
from app.price_parser import parse_lines

log = logging.getLogger(__name__)
router = APIRouter(prefix='/miniapp/api', dependencies=[])
attempts = {}
workers = {}
worker_states = {}
locks = {1: asyncio.Lock(), 2: asyncio.Lock()}

class ReaderAccount(Base):
    __tablename__ = 'telegram_reader_accounts'
    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    encrypted_session: Mapped[str] = mapped_column(Text)
    chats_json: Mapped[str] = mapped_column(Text, default='[]')


def verify_init_data(raw, token, owner_id, now=None):
    if not raw or len(raw) > 8192:
        return False
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=64)
        data = dict(pairs)
        if len(pairs) != len(data):
            return False
        received = data.pop('hash')
        check = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
        secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            return False
        age = (time.time() if now is None else now) - int(data['auth_date'])
        user = json.loads(data['user'])
        return -30 <= age <= 3600 and type(user.get('id')) is int and user['id'] == owner_id
    except (ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return False


def owner(x_telegram_init_data: str = Header(default='')):
    if os.getenv('VOLT_MINIAPP_ENABLED') != '1':
        raise HTTPException(503, 'Mini App отключено')
    token, owner_id = os.getenv('TG_BOT_TOKEN', ''), os.getenv('VOLT_OWNER_TG_ID', '')
    if not token or not owner_id.isdigit() or not verify_init_data(x_telegram_init_data, token, int(owner_id)):
        raise HTTPException(401, 'Откройте приложение заново из Telegram под аккаунтом владельца')


def settings():
    try:
        api_id = int(os.environ['TG_API_ID'])
        api_hash = os.environ['TG_API_HASH']
        cipher = Fernet(os.environ['VOLT_SESSION_ENCRYPTION_KEY'].encode())
        if api_id <= 0 or not api_hash:
            raise ValueError()
        return api_id, api_hash, cipher
    except (KeyError, ValueError, TypeError):
        raise RuntimeError('TG_API_ID, TG_API_HASH and a valid VOLT_SESSION_ENCRYPTION_KEY are required') from None


def validate_slot(slot):
    if slot not in (1, 2):
        raise HTTPException(404, 'Аккаунт не найден')


def saved(slot):
    with Sessions() as db:
        row = db.get(ReaderAccount, slot)
        if not row:
            return None
        return {'slot': slot, 'telegram_id': row.telegram_id, 'name': row.display_name,
                'session': row.encrypted_session, 'chats': json.loads(row.chats_json)}


async def reader_worker(slot):
    while True:
        data = saved(slot)
        if not data or not data['chats']:
            worker_states[slot] = 'not_configured'
            return
        try:
            api_id, api_hash, cipher = settings()
            session_string = cipher.decrypt(data['session'].encode()).decode()
            worker_states[slot] = 'connecting'
            await monitor_account({'name': f"miniapp-{data['telegram_id']}", 'chats': data['chats'],
                                   'session_string': session_string, 'api_id': api_id,
                                   'api_hash': api_hash, 'on_ready': lambda: worker_states.__setitem__(slot, 'monitoring')}, Sessions)
            worker_states[slot] = 'disconnected'
        except asyncio.CancelledError:
            raise
        except Exception:
            # No exception text: it can contain sensitive account or chat data.
            log.error('Reader slot %s failed; retrying in 30 seconds', slot)
            worker_states[slot] = 'retrying'
        await asyncio.sleep(30)


async def stop_worker(slot):
    task = workers.pop(slot, None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    worker_states[slot] = 'not_configured'


async def restart_worker(slot):
    await stop_worker(slot)
    data = saved(slot)
    if data and data['chats']:
        workers[slot] = asyncio.create_task(reader_worker(slot))


async def start():
    if os.getenv('VOLT_MINIAPP_ENABLED') != '1':
        return
    from app.main import engine, db_url
    if not db_url.startswith('postgresql+psycopg://'):
        raise RuntimeError('Mini App reader accounts require PostgreSQL')
    if os.getenv('WEB_CONCURRENCY', '1') != '1' or os.getenv('VOLT_COLLECTOR_ENABLED') == '1':
        raise RuntimeError('Mini App requires one worker and the legacy collector disabled')
    if not os.getenv('TG_BOT_TOKEN') or not os.getenv('VOLT_OWNER_TG_ID', '').isdigit():
        raise RuntimeError('Mini App requires TG_BOT_TOKEN and VOLT_OWNER_TG_ID')
    settings()
    Base.metadata.create_all(engine)
    CollectorBase.metadata.create_all(engine)
    for slot in (1, 2):
        await restart_worker(slot)


async def stop():
    for slot in (1, 2):
        await cancel_attempt(slot)
        await stop_worker(slot)


async def cancel_attempt(slot):
    attempt = attempts.pop(slot, None)
    if attempt:
        task = attempt.get('task')
        if task and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        else:
            await attempt['client'].disconnect()


async def complete_login(slot, attempt, qr):
    try:
        try:
            await qr.wait()
        except SessionPasswordNeededError:
            attempt['state'] = 'password_required'
            password = await asyncio.wait_for(attempt['password'].get(), timeout=180)
            try:
                await attempt['client'].sign_in(password=password)
            except PasswordHashInvalidError:
                attempt['state'] = 'password_invalid'
                return
            finally:
                password = None
        me = await attempt['client'].get_me()
        if not me or getattr(me, 'bot', False):
            raise RuntimeError('A Telegram user account is required')
        _, _, cipher = settings()
        encrypted = cipher.encrypt(attempt['client'].session.save().encode()).decode()
        # Disconnect before the monitor opens the same session.
        await attempt['client'].disconnect()
        with Sessions() as db:
            if db.get(ReaderAccount, slot) or db.scalar(select(ReaderAccount).where(ReaderAccount.telegram_id == str(me.id))):
                attempt['state'] = 'already_connected'
                return
            db.add(ReaderAccount(slot=slot, telegram_id=str(me.id),
                                 display_name=(me.first_name or 'Telegram')[:200],
                                 encrypted_session=encrypted, chats_json='[]'))
            db.commit()
        attempt['state'] = 'connected'
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        attempt['state'] = 'expired'
    except Exception:
        log.error('Telegram login failed for slot %s', slot)
        attempt['state'] = 'failed'
    finally:
        await attempt['client'].disconnect()
        attempt.pop('qr_image', None)


@router.get('/accounts', dependencies=[Depends(owner)])
async def accounts():
    result = []
    for slot in (1, 2):
        row = saved(slot)
        result.append({'slot': slot, 'connected': bool(row), 'name': row['name'] if row else None,
                       'chats': row['chats'] if row else [], 'monitor': worker_states.get(slot, 'not_configured'),
                       'login': attempts.get(slot, {}).get('state', 'idle')})
    return result


@router.get('/accounts/{slot}/messages', dependencies=[Depends(owner)])
def account_messages(slot: int, before: int | None = None):
    """Show saved messages only; never fetch, send or apply prices here."""
    validate_slot(slot)
    account = saved(slot)
    if not account:
        raise HTTPException(404, 'Сначала подключите аккаунт')
    with Sessions() as db:
        query = select(SupplierMessage).where(
            SupplierMessage.account == f"miniapp-{account['telegram_id']}"
        )
        if before is not None:
            query = query.where(SupplierMessage.id < before)
        rows = db.scalars(query.order_by(SupplierMessage.id.desc()).limit(21)).all()
        return {'messages': [{'id': row.id, 'chat_id': str(row.chat_id),
                               'message_id': row.message_id, 'text': row.text[:4000],
                               'truncated': len(row.text) > 4000,
                               'seen_at': row.seen_at.isoformat()} for row in rows[:20]],
                'next_before': rows[19].id if len(rows) > 20 else None}


@router.get('/accounts/{slot}/messages/{message_id}/preview', dependencies=[Depends(owner)])
def message_preview(slot: int, message_id: int):
    validate_slot(slot)
    account = saved(slot)
    if not account:
        raise HTTPException(404, 'Сначала подключите аккаунт')
    with Sessions() as db:
        row = db.scalar(select(SupplierMessage).where(
            SupplierMessage.id == message_id,
            SupplierMessage.account == f"miniapp-{account['telegram_id']}"))
        if row is None:
            raise HTTPException(404, 'Сообщение не найдено')
        if len(row.text) > 500000:
            raise HTTPException(422, 'Сообщение слишком большое для предварительного разбора')
        return parse_lines(row.text)


@router.post('/accounts/{slot}/login', dependencies=[Depends(owner)])
async def login(slot: int):
    validate_slot(slot)
    async with locks[slot]:
        if saved(slot):
            raise HTTPException(409, 'Сначала отключите существующий аккаунт')
        await cancel_attempt(slot)
        api_id, api_hash, _ = settings()
        client = TelegramClient(StringSession(), api_id, api_hash)
        try:
            await client.connect()
            qr = await client.qr_login()
            out = io.BytesIO()
            qrcode.make(qr.url).save(out, format='PNG')
            attempt = {'client': client, 'state': 'waiting', 'password': asyncio.Queue(maxsize=1),
                       'qr_image': base64.b64encode(out.getvalue()).decode()}
            attempts[slot] = attempt
            attempt['task'] = asyncio.create_task(complete_login(slot, attempt, qr))
            await asyncio.sleep(0)  # Install Telethon's login-token handler before returning the QR.
            return {'state': 'waiting', 'qr_image': attempt['qr_image']}
        except Exception:
            await client.disconnect()
            raise HTTPException(502, 'Не удалось начать вход в Telegram') from None


@router.get('/accounts/{slot}/login', dependencies=[Depends(owner)])
async def login_status(slot: int):
    validate_slot(slot)
    attempt = attempts.get(slot, {})
    return {'state': attempt.get('state', 'idle')}


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256, repr=False)

@router.post('/accounts/{slot}/password', dependencies=[Depends(owner)])
async def password(slot: int, body: PasswordIn):
    validate_slot(slot)
    async with locks[slot]:
        attempt = attempts.get(slot)
        if not attempt or attempt['state'] != 'password_required':
            raise HTTPException(409, 'Пароль сейчас не требуется')
        attempt['state'] = 'checking_password'
        attempt['password'].put_nowait(body.password)
    return {'state': 'checking_password'}


class ChatsIn(BaseModel):
    chats: list[str] = Field(max_length=30)

@router.put('/accounts/{slot}/chats', dependencies=[Depends(owner)])
async def configure_chats(slot: int, body: ChatsIn):
    validate_slot(slot)
    chats = [c.strip() for c in body.chats]
    if any(not c or len(c) > 128 or not (c.startswith('@') or c.lstrip('-').isdigit()) for c in chats) or len(set(chats)) != len(chats):
        raise HTTPException(422, 'Укажите уникальные @username или числовые ID чатов')
    values = [int(c) if c.lstrip('-').isdigit() else c for c in chats]
    async with locks[slot]:
        with Sessions() as db:
            row = db.get(ReaderAccount, slot)
            if not row:
                raise HTTPException(404, 'Сначала подключите аккаунт')
            row.chats_json = json.dumps(values, ensure_ascii=False)
            db.commit()
        await restart_worker(slot)
    return {'ok': True}


@router.delete('/accounts/{slot}', dependencies=[Depends(owner)])
async def disconnect(slot: int):
    validate_slot(slot)
    async with locks[slot]:
        await cancel_attempt(slot)
        await stop_worker(slot)
        with Sessions() as db:
            row = db.get(ReaderAccount, slot)
            if row:
                db.delete(row)
                db.commit()
    return {'ok': True}
