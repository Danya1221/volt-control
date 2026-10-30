"""Owner-only Telegram controls, including safe catalog-chat selection."""
import os
import secrets
import time
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
                           WebAppInfo, KeyboardButton, KeyboardButtonRequestChat,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)
from fastapi import HTTPException

CHAT_REQUEST_ID = 72103
# One short-lived candidate per owner, never the message contents.
forward_candidates = {}
log = logging.getLogger(__name__)


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


async def show_chat_picker(message, prompt=None):
    button = KeyboardButton(text='Выбрать чат для каталога', request_chat=KeyboardButtonRequestChat(
        request_id=CHAT_REQUEST_ID, chat_is_channel=False, bot_is_member=True, request_title=True))
    keyboard = ReplyKeyboardMarkup(keyboard=[[button]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer(prompt or 'Нажми кнопку и выбери чат. Сначала добавь в него этого бота администратором.', reply_markup=keyboard)


async def handle_forwarded_message(message, owner_id):
    if not is_owner(message, owner_id) or message.chat.type != 'private':
        return
    origin = message.forward_origin
    # A forwarded user message often contains only the author, not its source
    # group. MessageOriginChat identifies the sender chat, which can also be a
    # different chat: ask the owner to confirm before persisting a destination.
    candidate = getattr(origin, 'sender_chat', None) if getattr(origin, 'type', None) == 'chat' else None
    if candidate is None or candidate.type not in ('group', 'supergroup') or candidate.id >= 0:
        await show_chat_picker(message, 'Telegram не передал чат в пересланном сообщении. Выбери его кнопкой ниже. Сначала добавь в него бота администратором.')
        return
    for key, value in list(forward_candidates.items()):
        if value['owner_id'] == owner_id or value['expires'] <= time.monotonic():
            forward_candidates.pop(key, None)
    nonce = secrets.token_urlsafe(12)
    forward_candidates[nonce] = {'chat_id': candidate.id, 'owner_id': owner_id,
                                  'expires': time.monotonic() + 300}
    title = (candidate.title or 'чат')[:80]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Привязать этот чат', callback_data='forward_bind:' + nonce)],
        [InlineKeyboardButton(text='Выбрать другой чат', callback_data='select_catalog_chat')],
    ])
    await message.answer('Сообщение отправлено от имени чата «' + title + '». Это нужный чат для каталога?', reply_markup=keyboard)


async def confirm_forwarded_chat(callback, owner_id):
    if callback.from_user.id != owner_id or callback.message is None or callback.message.chat.type != 'private':
        await callback.answer('Доступ закрыт.', show_alert=True)
        return
    nonce = (callback.data or '').removeprefix('forward_bind:')
    candidate = forward_candidates.pop(nonce, None)
    if not candidate or candidate['owner_id'] != owner_id or candidate['expires'] <= time.monotonic():
        await callback.answer('Подтверждение устарело. Перешли сообщение заново.', show_alert=True)
        return
    if os.getenv('VOLT_MINIAPP_ENABLED') != '1':
        await callback.answer('Mini App выключено.', show_alert=True)
        return
    await callback.answer()
    from app.miniapp import bind_destination, DestinationIn
    try:
        result = await bind_destination(DestinationIn(chat=str(candidate['chat_id'])))
    except HTTPException as exc:
        await callback.message.answer(str(exc.detail) + '\nПовтори пересылку или выбери чат через /connectgroup.')
        return
    await callback.message.answer('Чат «' + result['title'] + '» привязан. Публикация пока выключена.')


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


async def register_topic_command(message, owner_id):
    if not is_owner(message, owner_id):
        return
    if message.chat.type != 'supergroup' or not getattr(message.chat, 'is_forum', False):
        return
    if os.getenv('VOLT_MINIAPP_ENABLED') != '1':
        return
    thread_id = getattr(message, 'message_thread_id', None) or 1
    name = (message.text or '').partition(' ')[2].strip()[:255]
    if not name:
        return
    from app.miniapp import register_catalog_topic
    try:
        await register_catalog_topic(message.chat.id, thread_id, name, message.bot)
    except HTTPException:
        return


def create_dispatcher(owner_id):
    dp = Dispatcher()

    async def observe_topics(handler, event, data):
        if os.getenv('VOLT_MINIAPP_ENABLED') == '1':
            try:
                from app.miniapp import observe_catalog_topic
                await observe_catalog_topic(event)
            except Exception:
                log.exception('Could not observe catalog topic')
        return await handler(event, data)

    dp.message.outer_middleware(observe_topics)

    @dp.message(F.forward_origin)
    async def forwarded_message(message: Message):
        await handle_forwarded_message(message, owner_id)

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
            await message.answer('⚡ VOLT Control\n\nОткрой панель, перешли сообщение из чата или выбери чат для каталога.', reply_markup=keyboard)
        else:
            await message.answer('⚡ VOLT Control\n\nMini App ещё не настроено. Коды авторизации и пароли в чат не отправляй.')

    @dp.message(Command('bindgroup'))
    async def bindgroup(message: Message):
        await bind_chat_command(message, owner_id)

    @dp.message(Command('volttopic'))
    async def volttopic(message: Message):
        await register_topic_command(message, owner_id)

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

    @dp.callback_query(F.data.startswith('forward_bind:'))
    async def bind_forwarded_chat(callback: CallbackQuery):
        await confirm_forwarded_chat(callback, owner_id)

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

