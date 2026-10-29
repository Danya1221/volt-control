"""Owner-only Telegram controls, including safe catalog-chat selection."""
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
                           WebAppInfo, KeyboardButton, KeyboardButtonRequestChat,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)
from fastapi import HTTPException

CHAT_REQUEST_ID = 72103


def is_owner(message, owner_id):
    return message.from_user is not None and message.from_user.id == owner_id and not message.sender_chat


async def bind_chat_command(message, owner_id):
    if not is_owner(message, owner_id):
        if message.sender_chat:
            await message.answer('Telegram скрыл твой аккаунт из-за анонимности администратора. Открой бота в личке и отправь /connectgroup.')
        else:
            await message.answer('Привязать чат может только владелец VOLT. Открой бота в личке и отправь /connectgroup.')
        return
    if message.chat.type not in ('group', 'supergroup'):
        await message.answer('Открой бота в личке и отправь /connectgroup, чтобы выбрать чат.')
        return
    if os.getenv('VOLT_MINIAPP_ENABLED') != '1':
        await message.answer('Сначала включи Mini App в настройках сервиса.')
        return
    from app.miniapp import bind_destination, DestinationIn
    try:
        await bind_destination(DestinationIn(chat=str(message.chat.id)))
    except HTTPException as exc:
        await message.answer(str(exc.detail))
        return
    await message.answer('Чат привязан к VOLT Control. Публикация пока выключена. Настройки находятся в разделе «Витрина».')


async def select_chat_command(message, owner_id):
    if not is_owner(message, owner_id):
        return
    if message.chat.type != 'private':
        await message.answer('Отправь /connectgroup в личном чате с ботом.')
        return
    await show_chat_picker(message)


async def show_chat_picker(message):
    button = KeyboardButton(text='Выбрать чат для каталога', request_chat=KeyboardButtonRequestChat(
        request_id=CHAT_REQUEST_ID, chat_is_channel=False, bot_is_member=True, request_title=True))
    keyboard = ReplyKeyboardMarkup(keyboard=[[button]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer('Нажми кнопку и выбери чат. Сначала добавь в него этого бота администратором.', reply_markup=keyboard)


async def accept_selected_chat(message, owner_id):
    if not is_owner(message, owner_id) or message.chat.type != 'private':
        return
    shared = message.chat_shared
    if shared is None or shared.request_id != CHAT_REQUEST_ID:
        return
    if os.getenv('VOLT_MINIAPP_ENABLED') != '1':
        await message.answer('Сначала включи Mini App в настройках сервиса.', reply_markup=ReplyKeyboardRemove())
        return
    from app.miniapp import bind_destination, DestinationIn
    try:
        result = await bind_destination(DestinationIn(chat=str(shared.chat_id)))
    except HTTPException as exc:
        await message.answer(str(exc.detail) + '\nПовтори /connectgroup после исправления.', reply_markup=ReplyKeyboardRemove())
        return
    await message.answer('Чат «' + result['title'] + '» привязан. Публикация пока выключена.', reply_markup=ReplyKeyboardRemove())


def create_dispatcher(owner_id):
    dp = Dispatcher()

    @dp.message(Command('myid'))
    async def myid(message: Message):
        if message.from_user:
            await message.answer(f'Твой Telegram ID: {message.from_user.id}')

    @dp.message(Command('start'))
    async def start(message: Message):
        if message.from_user is None or message.from_user.id != owner_id:
            await message.answer('Доступ закрыт.')
            return
        url = os.getenv('VOLT_MINIAPP_URL', '')
        if os.getenv('VOLT_MINIAPP_ENABLED') == '1' and url.startswith('https://'):
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='Открыть VOLT Control', web_app=WebAppInfo(url=url))],
                [InlineKeyboardButton(text='Привязать чат', callback_data='select_catalog_chat')],
            ])
            await message.answer('⚡ VOLT Control\n\nОткрой панель или выбери чат для каталога.', reply_markup=keyboard)
        else:
            await message.answer('⚡ VOLT Control\n\nMini App ещё не настроено. Коды авторизации и пароли в чат не отправляй.')

    @dp.message(Command('bindgroup'))
    async def bindgroup(message: Message):
        await bind_chat_command(message, owner_id)

    @dp.message(Command('connectgroup'))
    async def connectgroup(message: Message):
        await select_chat_command(message, owner_id)

    @dp.callback_query(F.data == 'select_catalog_chat')
    async def select_catalog_chat(callback: CallbackQuery):
        if callback.from_user.id != owner_id or callback.message is None or callback.message.chat.type != 'private':
            await callback.answer('Доступ закрыт.', show_alert=True)
            return
        await callback.answer()
        await show_chat_picker(callback.message)

    @dp.message(F.chat_shared)
    async def chat_shared(message: Message):
        await accept_selected_chat(message, owner_id)

    @dp.message(Command('status'))
    async def status(message: Message):
        if message.from_user is None or message.from_user.id != owner_id:
            return
        await message.answer('⚡ VOLT Control: сервер работает. Мониторинг поставщиков настраивается отдельно.')

    @dp.message()
    async def other(message: Message):
        if not is_owner(message, owner_id) or message.chat.type != 'private':
            return
        await message.answer('Доступные команды: /start, /status, /connectgroup. Не отправляй сюда коды входа.')

    return dp


async def run_bot(on_started=None):
    token = os.environ['TG_BOT_TOKEN']
    owner_raw = os.environ.get('VOLT_OWNER_TG_ID', '')
    if not owner_raw.isdigit():
        raise RuntimeError('VOLT_OWNER_TG_ID must be configured before enabling the bot')
    bot = Bot(token=token)
    dp = create_dispatcher(int(owner_raw))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await bot.get_me()
        if on_started:
            on_started()
        await dp.start_polling(bot, handle_signals=False)
    finally:
        await bot.session.close()
