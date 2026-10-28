"""Read-only Telegram supplier message collection.

Uses Telethon user sessions. It NEVER sends Telegram messages, applies price
batches, or changes catalog data. Persist message snapshots for later review.
"""
import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, events

SCHEMA = """
CREATE TABLE IF NOT EXISTS supplier_messages (
 account TEXT NOT NULL,
 chat_id INTEGER NOT NULL,
 message_id INTEGER NOT NULL,
 text TEXT NOT NULL,
 edited_at TEXT,
 seen_at TEXT NOT NULL,
 PRIMARY KEY(account, chat_id, message_id)
);
CREATE TABLE IF NOT EXISTS chat_cursors (
 account TEXT NOT NULL,
 chat_id INTEGER NOT NULL,
 last_id INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(account, chat_id)
);
"""

class MessageStore:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def save(self, account: str, chat_id: int, message_id: int, text: str, edited_at=None):
        if not text.strip():
            return
        stamp = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO supplier_messages(account,chat_id,message_id,text,edited_at,seen_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(account,chat_id,message_id)
               DO UPDATE SET text=excluded.text,edited_at=excluded.edited_at,seen_at=excluded.seen_at""",
            (account,chat_id,message_id,text,
             edited_at.isoformat() if hasattr(edited_at, "isoformat") else None,stamp))
        self.conn.commit()

    def cursor(self, account: str, chat_id: int) -> int:
        row=self.conn.execute(
            "SELECT last_id FROM chat_cursors WHERE account=? AND chat_id=?",
            (account,chat_id)).fetchone()
        return row[0] if row else 0

    def advance(self, account: str, chat_id: int, message_id: int):
        self.conn.execute(
            """INSERT INTO chat_cursors(account,chat_id,last_id) VALUES(?,?,?)
               ON CONFLICT(account,chat_id) DO UPDATE SET
               last_id=MAX(chat_cursors.last_id,excluded.last_id)""",
            (account,chat_id,message_id))
        self.conn.commit()

async def run_account(config: dict, store: MessageStore):
    label=config["name"]
    api_id=int(os.environ[config["api_id_env"]])
    api_hash=os.environ[config["api_hash_env"]]
    session=config["session"]
    chats=config["chats"]
    if not chats:
        raise ValueError(f"{label}: at least one explicit chat is required")
    async with TelegramClient(session,api_id,api_hash) as client:
        if not await client.is_user_authorized():
            raise RuntimeError(f"{label}: session not authorized; authorize locally first")
        entities={}
        for chat in chats:
            entity=await client.get_entity(chat)
            peer=await client.get_peer_id(entity)
            entities[peer]=entity

        @client.on(events.NewMessage(chats=list(entities.values())))
        async def on_new(event):
            store.save(label,event.chat_id,event.id,event.raw_text or "",event.message.edit_date)
            store.advance(label,event.chat_id,event.id)

        @client.on(events.MessageEdited(chats=list(entities.values())))
        async def on_edit(event):
            store.save(label,event.chat_id,event.id,event.raw_text or "",event.message.edit_date)

        # Catch up missing messages after a restart before waiting for events.
        # Re-read recent history to capture edits to previously seen messages.
        for peer,entity in entities.items():
            cursor=store.cursor(label,peer)
            async for message in client.iter_messages(entity,min_id=cursor,reverse=True):
                store.save(label,peer,message.id,message.raw_text or "",message.edit_date)
                store.advance(label,peer,message.id)
            async for message in client.iter_messages(entity,limit=200):
                store.save(label,peer,message.id,message.raw_text or "",message.edit_date)

        print(f"[{label}] monitoring {len(entities)} chats; read-only")
        await client.run_until_disconnected()

async def main():
    config_path=os.environ.get("VOLT_SUPPLIER_CONFIG","supplier_accounts.json")
    config=json.loads(Path(config_path).read_text(encoding="utf-8"))
    accounts=config.get("accounts",[])
    if not accounts or len(accounts)>2:
        raise ValueError("Configure one or two supplier accounts")
    store=MessageStore(os.environ.get("VOLT_SUPPLIER_DB","data/supplier_messages.sqlite3"))
    await asyncio.gather(*(run_account(account,store) for account in accounts))

if __name__=="__main__":
    asyncio.run(main())
