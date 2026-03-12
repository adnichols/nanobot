from types import SimpleNamespace

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TelegramChannel
from nanobot.config.schema import TelegramConfig


class _FakeMessage:
    def __init__(
        self,
        *,
        text: str,
        chat_id: int = 123,
        message_id: int = 456,
        chat_type: str = "private",
    ) -> None:
        self.text = text
        self.caption = None
        self.photo = None
        self.voice = None
        self.audio = None
        self.document = None
        self.chat_id = chat_id
        self.message_id = message_id
        self.chat = SimpleNamespace(type=chat_type)
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


def _make_channel() -> TelegramChannel:
    return TelegramChannel(
        TelegramConfig(enabled=True, token="token", allow_from=["*"]),
        MessageBus(),
    )


def _make_update(
    text: str,
    *,
    chat_type: str = "private",
    username: str = "alice",
    first_name: str = "Alice",
) -> SimpleNamespace:
    message = _FakeMessage(text=text, chat_type=chat_type)
    user = SimpleNamespace(id=42, username=username, first_name=first_name)
    return SimpleNamespace(message=message, effective_user=user)


def _make_context(bot_username: str = "nanobot") -> SimpleNamespace:
    return SimpleNamespace(bot=SimpleNamespace(username=bot_username))


@pytest.mark.asyncio
async def test_unknown_slash_command_forwards_to_bus(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("/model openai/gpt-5.4")
    context = _make_context()
    handled: list[dict[str, object]] = []
    typing_calls: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)
    monkeypatch.setattr(channel, "_start_typing", typing_calls.append)

    await channel._forward_command(update, context)

    assert typing_calls == ["123"]
    assert handled == [
        {
            "sender_id": "42|alice",
            "chat_id": "123",
            "content": "/model openai/gpt-5.4",
            "metadata": {
                "message_id": 456,
                "user_id": 42,
                "username": "alice",
                "first_name": "Alice",
                "is_group": False,
            },
        }
    ]


@pytest.mark.asyncio
async def test_stop_command_forwards_to_bus_for_local_handling(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("/stop")
    context = _make_context()
    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)
    monkeypatch.setattr(channel, "_start_typing", lambda chat_id: None)

    await channel._forward_command(update, context)

    assert len(handled) == 1
    assert handled[0]["content"] == "/stop"


@pytest.mark.asyncio
async def test_new_command_forwards_to_bus_for_local_handling(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("/new")
    context = _make_context()
    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)
    monkeypatch.setattr(channel, "_start_typing", lambda chat_id: None)

    await channel._forward_command(update, context)

    assert len(handled) == 1
    assert handled[0]["content"] == "/new"


@pytest.mark.asyncio
async def test_group_command_bot_mention_is_normalized(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("/init@nanobot repo", chat_type="group")
    context = _make_context()
    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)
    monkeypatch.setattr(channel, "_start_typing", lambda chat_id: None)

    await channel._forward_command(update, context)

    assert len(handled) == 1
    assert handled[0]["content"] == "/init repo"


@pytest.mark.asyncio
async def test_multiline_group_command_bot_mention_is_normalized(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("/init@nanobot\nrepo", chat_type="group")
    context = _make_context()
    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)
    monkeypatch.setattr(channel, "_start_typing", lambda chat_id: None)

    await channel._forward_command(update, context)

    assert len(handled) == 1
    assert handled[0]["content"] == "/init\nrepo"


@pytest.mark.asyncio
async def test_group_command_for_other_bot_is_ignored(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("/init@otherbot repo", chat_type="group")
    context = _make_context()
    handled: list[dict[str, object]] = []
    typing_calls: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)
    monkeypatch.setattr(channel, "_start_typing", typing_calls.append)

    await channel._forward_command(update, context)

    assert typing_calls == []
    assert handled == []


@pytest.mark.asyncio
async def test_start_command_handles_locally(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("/start")
    forwarded: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        forwarded.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)

    await channel._on_start(update, None)

    assert forwarded == []
    assert len(update.message.replies) == 1
    assert "Hi Alice" in update.message.replies[0]


@pytest.mark.asyncio
async def test_help_command_handles_locally(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("/help")
    forwarded: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        forwarded.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)

    await channel._on_help(update, None)

    assert forwarded == []
    assert len(update.message.replies) == 1
    assert "/new" in update.message.replies[0]
    assert "/stop" in update.message.replies[0]
    assert "/help" in update.message.replies[0]


@pytest.mark.asyncio
async def test_slash_command_forwarding_includes_message_metadata(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("/status", chat_type="group", username="bob", first_name="Bob")
    context = _make_context()
    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)
    monkeypatch.setattr(channel, "_start_typing", lambda chat_id: None)

    await channel._forward_command(update, context)

    assert handled[0]["metadata"] == {
        "message_id": 456,
        "user_id": 42,
        "username": "bob",
        "first_name": "Bob",
        "is_group": True,
    }


@pytest.mark.asyncio
async def test_plain_text_still_routes_through_message_handler(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("hello world")
    handled: list[dict[str, object]] = []
    typing_calls: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)
    monkeypatch.setattr(channel, "_start_typing", typing_calls.append)

    await channel._on_message(update, None)

    assert typing_calls == ["123"]
    assert channel._chat_ids == {"42|alice": 123}
    assert handled == [
        {
            "sender_id": "42|alice",
            "chat_id": "123",
            "content": "hello world",
            "media": [],
            "metadata": {
                "message_id": 456,
                "user_id": 42,
                "username": "alice",
                "first_name": "Alice",
                "is_group": False,
            },
        }
    ]


@pytest.mark.asyncio
async def test_malformed_group_command_does_not_forward_invalid_content(monkeypatch) -> None:
    channel = _make_channel()
    update = _make_update("/@nanobot repo", chat_type="group")
    context = _make_context()
    handled: list[dict[str, object]] = []
    typing_calls: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)
    monkeypatch.setattr(channel, "_start_typing", typing_calls.append)

    await channel._forward_command(update, context)

    assert typing_calls == []
    assert handled == []
