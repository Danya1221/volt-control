"""Generate a Telethon StringSession locally. NEVER share the output.

Run: python scripts/authorize_telegram.py
"""
import asyncio
import getpass
from telethon import TelegramClient
from telethon.sessions import StringSession

async def main():
    print("VOLT Control: local Telegram authorization")
    print("Keep the resulting session string secret. Paste it only into Railway Variables.")
    api_id = int(input("Telegram API_ID: ").strip())
    api_hash = getpass.getpass("Telegram API_HASH (hidden): ").strip()
    phone = input("Phone number with country code (+...): ").strip()
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        await client.start(phone=lambda: phone)
        me = await client.get_me()
        print(f"Authorized Telegram account ID: {me.id}")
        print("Copy the following session to Railway TG_SESSION_N (do not send it in chat):")
        print(client.session.save())

if __name__ == "__main__":
    asyncio.run(main())
