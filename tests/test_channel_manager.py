"""Tests for channel manager progress visibility filtering."""

from __future__ import annotations

import asyncio

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class _FakeChannel:
    def __init__(self) -> None:
        self.is_running = True
        self.sent: list[OutboundMessage] = []

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.is_running = False


@pytest.mark.asyncio
async def test_dispatch_outbound_filters_acp_progress_by_visibility_kind() -> None:
    config = Config()
    config.channels.send_progress = True
    config.channels.acp_show_thinking = True
    config.channels.acp_show_tool_calls = False
    config.channels.acp_show_tool_results = True
    config.channels.acp_show_system = False

    bus = MessageBus()
    manager = ChannelManager(config, bus)
    fake_channel = _FakeChannel()
    manager.channels = {"telegram": fake_channel}

    task = asyncio.create_task(manager._dispatch_outbound())
    try:
        await bus.publish_outbound(
            OutboundMessage(
                channel="telegram",
                chat_id="123",
                content="thinking",
                metadata={"_progress": True, "_progress_kind": "thinking"},
            )
        )
        await bus.publish_outbound(
            OutboundMessage(
                channel="telegram",
                chat_id="123",
                content="tool call",
                metadata={"_progress": True, "_progress_kind": "tool_call"},
            )
        )
        await bus.publish_outbound(
            OutboundMessage(
                channel="telegram",
                chat_id="123",
                content="tool result",
                metadata={"_progress": True, "_progress_kind": "tool_result"},
            )
        )
        await bus.publish_outbound(
            OutboundMessage(
                channel="telegram",
                chat_id="123",
                content="system",
                metadata={"_progress": True, "_progress_kind": "system"},
            )
        )

        await asyncio.sleep(0.05)
    finally:
        task.cancel()
        await task

    assert [msg.content for msg in fake_channel.sent] == ["thinking", "tool result"]
