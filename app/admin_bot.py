"""Owner-only Telegram bot entry point for VOLT Control.

No Telegram account login codes, passwords, or session strings are accepted.
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

logger = logging.getLogger(__name__)

async def run_bot():
    token = os.environ["TG_BOT_TOKEN"]
    owner_raw = os.environ.get("VOLT_OWNER_TG_ID", "")
    if not owner_raw.isdigit():
        raise RuntimeError("VOLT_OWNER_TG_ID must be configured before enabling the bot")
    owner_id = int(owner_raw)
    bot = Bot(token=token)
    dp = Dispatcher()

    @dp.message(Command("myid"))
    async def myid(message: Message):
        if message.from_user:
            await message.answer(f"Твой Telegram ID: {message.from_user.id}")

    @dp.message(Command("start"))
    async def start(message: Message):
        if message.from_user is None or message.from_user.id != owner_id:
            await message.answer("Доступ закрыт.")
            return
        url = os.getenv('VOLT_MINIAPP_URL', '')
        if os.getenv('VOLT_MINIAPP_ENABLED') == '1' and url.startswith('https://'):
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='Открыть VOLT Control', web_app=WebAppInfo(url=url))
            ]])
            await message.answer('⚡ VOLT Control\n\nОткрой панель для подключения аккаунтов.', reply_markup=keyboard)
        else:
            await message.answer('⚡ VOLT Control\n\nMini App ещё не настроено. Коды авторизации и пароли в чат не отправляй.')

    @dp.message(Command("status"))
    async def status(message: Message):
        if message.from_user is None or message.from_user.id != owner_id:
            return
        await message.answer("⚡ VOLT Control: сервер работает. Мониторинг поставщиков настраивается отдельно.")

    @dp.message()
    async def other(message: Message):
        if message.from_user is None or message.from_user.id != owner_id:
            return
        await message.answer("Доступные команды: /start, /status. Не отправляй сюда коды входа.")

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, handle_signals=False)
    finally:
        await bot.session.close()

