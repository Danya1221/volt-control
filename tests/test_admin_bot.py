import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

import app.main as main
from app import admin_bot, miniapp


def message(user_id=123, chat_type='private', sender_chat=None, shared=None):
    return SimpleNamespace(from_user=SimpleNamespace(id=user_id), chat=SimpleNamespace(type=chat_type, id=-10099),
                           sender_chat=sender_chat, chat_shared=shared, answer=AsyncMock())


def test_group_selection_keyboard_is_owner_only():
    async def scenario():
        outsider = message(user_id=456)
        await admin_bot.select_chat_command(outsider, 123)
        outsider.answer.assert_not_awaited()
        owner = message()
        await admin_bot.select_chat_command(owner, 123)
        kwargs = owner.answer.await_args.kwargs
        request = kwargs['reply_markup'].keyboard[0][0].request_chat
        assert request.request_id == admin_bot.CHAT_REQUEST_ID
        assert request.chat_is_channel is False and request.bot_is_member is True
        assert request.chat_is_forum is None
    asyncio.run(scenario())


def test_chat_shared_checks_owner_and_request(monkeypatch):
    monkeypatch.setenv('VOLT_MINIAPP_ENABLED', '1')
    bind = AsyncMock(return_value={'title': 'My group'})
    monkeypatch.setattr(miniapp, 'bind_destination', bind)
    async def scenario():
        bad = message(user_id=456, shared=SimpleNamespace(request_id=admin_bot.CHAT_REQUEST_ID, chat_id=-10099))
        await admin_bot.accept_selected_chat(bad, 123)
        bind.assert_not_awaited()
        other = message(shared=SimpleNamespace(request_id=1, chat_id=-10099))
        await admin_bot.accept_selected_chat(other, 123)
        bind.assert_not_awaited()
        good = message(shared=SimpleNamespace(request_id=admin_bot.CHAT_REQUEST_ID, chat_id=-10099))
        await admin_bot.accept_selected_chat(good, 123)
        assert bind.await_args.args[0].chat == '-10099'
        assert 'My group' in good.answer.await_args.args[0]
        bind.side_effect = HTTPException(422, 'Нет прав бота')
        failed = message(shared=SimpleNamespace(request_id=admin_bot.CHAT_REQUEST_ID, chat_id=-10099))
        await admin_bot.accept_selected_chat(failed, 123)
        assert 'Нет прав бота' in failed.answer.await_args.args[0]
    asyncio.run(scenario())


def test_bind_command_explains_anonymous_or_wrong_owner(monkeypatch):
    monkeypatch.setenv('VOLT_MINIAPP_ENABLED', '1')
    bind = AsyncMock(return_value={'title': 'Group'})
    monkeypatch.setattr(miniapp, 'bind_destination', bind)
    async def scenario():
        anonymous = message(user_id=1087968824, chat_type='supergroup', sender_chat=SimpleNamespace(id=-10099))
        await admin_bot.bind_chat_command(anonymous, 123)
        assert '/connectgroup' in anonymous.answer.await_args.args[0]
        bind.assert_not_awaited()
        wrong = message(user_id=456, chat_type='supergroup')
        await admin_bot.bind_chat_command(wrong, 123)
        assert 'владелец' in wrong.answer.await_args.args[0].lower()
        bind.assert_not_awaited()
        correct = message(chat_type='supergroup')
        await admin_bot.bind_chat_command(correct, 123)
        bind.assert_awaited_once()
        assert 'привязан' in correct.answer.await_args.args[0]
    asyncio.run(scenario())


def test_bot_supervisor_updates_health_and_retries(monkeypatch):
    started = []
    async def failing_bot(on_started):
        on_started()
        started.append(main.bot_status['state'])
        raise RuntimeError('sensitive detail must not be logged')
    async def stop_retry(_):
        raise asyncio.CancelledError()
    monkeypatch.setattr(admin_bot, 'run_bot', failing_bot)
    monkeypatch.setattr(main.asyncio, 'sleep', stop_retry)
    async def scenario():
        try:
            await main.bot_supervisor()
        except asyncio.CancelledError:
            pass
        assert started == ['started']
        assert main.bot_status['state'] == 'retrying'
        assert main.health()['bot'] == 'retrying'
    asyncio.run(scenario())
    main.bot_status['state'] = 'disabled'


def test_chat_button_only_opens_owner_picker():
    dispatcher = admin_bot.create_dispatcher(123)
    handler = next(item.callback for item in dispatcher.callback_query.handlers
                   if item.callback.__name__ == 'select_catalog_chat')
    async def scenario():
        reply = message()
        wrong = SimpleNamespace(from_user=SimpleNamespace(id=456), message=reply, answer=AsyncMock())
        await handler(wrong)
        reply.answer.assert_not_awaited()
        assert wrong.answer.await_args.kwargs['show_alert'] is True
        correct = SimpleNamespace(from_user=SimpleNamespace(id=123), message=reply, answer=AsyncMock())
        await handler(correct)
        assert reply.answer.await_args.kwargs['reply_markup'].keyboard[0][0].request_chat.request_id == admin_bot.CHAT_REQUEST_ID
    asyncio.run(scenario())



def test_forwarded_group_requires_confirmation_and_checks_owner(monkeypatch):
    monkeypatch.setenv('VOLT_MINIAPP_ENABLED', '1')
    admin_bot.forward_candidates.clear()
    bind = AsyncMock(return_value={'title': 'Retail chat'})
    monkeypatch.setattr(miniapp, 'bind_destination', bind)
    async def scenario():
        fwd = message()
        fwd.forward_origin = SimpleNamespace(type='chat', sender_chat=SimpleNamespace(id=-10099, type='supergroup', title='Retail chat'))
        await admin_bot.handle_forwarded_message(fwd, 123)
        bind.assert_not_awaited()
        kb = fwd.answer.await_args.kwargs['reply_markup']
        data = kb.inline_keyboard[0][0].callback_data
        assert data.startswith('forward_bind:')
        reply = message()
        outsider = SimpleNamespace(from_user=SimpleNamespace(id=456), message=reply, data=data, answer=AsyncMock())
        await admin_bot.confirm_forwarded_chat(outsider, 123)
        bind.assert_not_awaited()
        assert outsider.answer.await_args.kwargs['show_alert'] is True
        owner = SimpleNamespace(from_user=SimpleNamespace(id=123), message=reply, data=data, answer=AsyncMock())
        await admin_bot.confirm_forwarded_chat(owner, 123)
        assert bind.await_args.args[0].chat == '-10099'
        assert 'Retail chat' in reply.answer.await_args.args[0]
        await admin_bot.confirm_forwarded_chat(owner, 123)
        assert bind.await_count == 1
        assert owner.answer.await_args.kwargs['show_alert'] is True
    asyncio.run(scenario())
    admin_bot.forward_candidates.clear()


def test_forward_without_source_offers_picker_without_binding(monkeypatch):
    bind = AsyncMock()
    monkeypatch.setattr(miniapp, 'bind_destination', bind)
    async def scenario():
        for origin in [SimpleNamespace(type='user', sender_user=SimpleNamespace(id=42)),
                       SimpleNamespace(type='hidden_user'),
                       SimpleNamespace(type='channel', chat=SimpleNamespace(id=-10000, type='channel'))]:
            fwd = message()
            fwd.forward_origin = origin
            await admin_bot.handle_forwarded_message(fwd, 123)
            assert 'не передал' in fwd.answer.await_args.args[0]
            request = fwd.answer.await_args.kwargs['reply_markup'].keyboard[0][0].request_chat
            assert request.request_id == admin_bot.CHAT_REQUEST_ID
        bind.assert_not_awaited()
    asyncio.run(scenario())


def test_forward_handler_precedes_generic_and_commands():
    dispatcher = admin_bot.create_dispatcher(123)
    names = [item.callback.__name__ for item in dispatcher.message.handlers]
    assert names.index('forwarded_message') < names.index('other')
    assert names.index('forwarded_message') < names.index('start')
