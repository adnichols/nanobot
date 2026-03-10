"""Tests for ACP update rendering.

These tests verify:
- Tool update rendering
- Chunk accumulation across multiple updates
- Final answer emission after chunks
- Duplicate suppression (identical payloads suppressed)
- Permission-state rendering from ACP-06
- Integration with fake agent fixtures
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

import pytest

from nanobot.acp.render import ACPRenderer
from nanobot.acp.types import (
    ACPPermissionDecision,
    ACPPermissionRequest,
    ACPRenderedUpdate,
    ACPStreamChunk,
    ACPStreamChunkType,
    ACPUpdateEvent,
)
from nanobot.acp.updates import ACPDirectUpdateSink, ACPUpdateAccumulator
from nanobot.bus.queue import MessageBus


@dataclass
class RenderedPayload:
    """A deterministic representation of a rendered update payload."""

    update_type: str
    content: str
    correlation_id: Optional[str] = None
    session_id: Optional[str] = None


class FakeUpdateSink:
    """Fake update sink for testing."""

    def __init__(self):
        self.updates: list[ACPUpdateEvent] = []
        self.rendered: list[ACPRenderedUpdate] = []
        self.stream_chunks: list[ACPStreamChunk] = []

    async def send_update(self, event: ACPUpdateEvent) -> None:
        self.updates.append(event)

    async def send_rendered(self, update: ACPRenderedUpdate) -> None:
        self.rendered.append(update)

    async def stream_chunk(self, chunk: ACPStreamChunk) -> None:
        self.stream_chunks.append(chunk)


class FakePermissionBroker:
    """Fake permission broker for testing."""

    def __init__(self):
        self.requests: list[ACPPermissionRequest] = []
        self.decisions: list[ACPPermissionDecision] = []

    async def request_permission(self, request: ACPPermissionRequest) -> ACPPermissionDecision:
        self.requests.append(request)
        # Auto-approve for testing
        decision = ACPPermissionDecision(
            request_id=request.id,
            granted=True,
            reason="Auto-approved for testing",
            timestamp=datetime.now(UTC),
        )
        self.decisions.append(decision)
        return decision


class TestToolUpdateRendering:
    """Tests for tool update rendering."""

    @pytest.fixture
    def message_bus(self):
        """Provide a message bus."""
        return MessageBus()

    @pytest.fixture
    def update_sink(self):
        """Provide a fake update sink."""
        return FakeUpdateSink()

    @pytest.fixture
    def permission_broker(self):
        """Provide a fake permission broker."""
        return FakePermissionBroker()

    @pytest.mark.asyncio
    async def test_tool_progress_renders_to_outbound_message(
        self, message_bus, update_sink, permission_broker
    ):
        """Given an ACP agent streams tool progress, when nanobot receives updates,
        then the user sees sensible incremental progress."""
        # Create the accumulator and renderer
        accumulator = ACPUpdateAccumulator(update_sink)
        renderer = ACPRenderer(
            message_bus=message_bus,
            permission_broker=permission_broker,
        )

        # Subscribe the renderer to the accumulator
        accumulator.subscribe(renderer)

        # Simulate tool use start update
        tool_start_event = ACPUpdateEvent(
            event_type="tool_use_start",
            timestamp=datetime.now(UTC),
            payload={
                "tool_name": "read",
                "tool_input": {"path": "/home/user/test.txt"},
                "tool_use_id": "tool-123",
            },
            correlation_id="prompt-123",
        )
        await accumulator.receive_update(tool_start_event)

        # Consume the outbound message
        outbound = await message_bus.consume_outbound()

        # Verify the outbound message contains tool progress
        assert outbound.channel == "acp"
        assert "read" in outbound.content.lower() or "tool" in outbound.content.lower()

    @pytest.mark.asyncio
    async def test_tool_result_renders_to_outbound_message(
        self, message_bus, update_sink, permission_broker
    ):
        """Given a tool completes, when nanobot receives the result,
        then the user sees the tool result."""
        accumulator = ACPUpdateAccumulator(update_sink)
        renderer = ACPRenderer(
            message_bus=message_bus,
            permission_broker=permission_broker,
        )
        accumulator.subscribe(renderer)

        # Simulate tool result
        tool_result_event = ACPUpdateEvent(
            event_type="tool_result",
            timestamp=datetime.now(UTC),
            payload={
                "tool_name": "read",
                "tool_use_id": "tool-123",
                "content": "File content: Hello World",
            },
            correlation_id="prompt-123",
        )
        await accumulator.receive_update(tool_result_event)

        outbound = await message_bus.consume_outbound()
        assert outbound.content is not None


class TestChunkAccumulation:
    """Tests for message chunk accumulation."""

    @pytest.fixture
    def message_bus(self):
        return MessageBus()

    @pytest.fixture
    def update_sink(self):
        return FakeUpdateSink()

    @pytest.fixture
    def permission_broker(self):
        return FakePermissionBroker()

    @pytest.mark.asyncio
    async def test_multiple_chunks_accumulate_correctly(
        self, message_bus, update_sink, permission_broker
    ):
        """Given multiple content chunks arrive, when rendering runs,
        then all chunks are accumulated before emission."""
        accumulator = ACPUpdateAccumulator(update_sink)
        renderer = ACPRenderer(
            message_bus=message_bus,
            permission_broker=permission_broker,
        )
        accumulator.subscribe(renderer)

        # Send prompt_start to establish correlation context
        prompt_start = ACPUpdateEvent(
            event_type="prompt_start",
            timestamp=datetime.now(UTC),
            payload={"content": "Test prompt"},
            correlation_id="prompt-123",
        )
        await accumulator.receive_update(prompt_start)

        # Simulate multiple chunks
        for i in range(3):
            chunk = ACPStreamChunk(
                type=ACPStreamChunkType.CONTENT_DELTA,
                content=f"Part {i + 1}: ",
            )
            await accumulator.receive_chunk(chunk, correlation_id="prompt-123")

        # Send prompt_end to trigger emission
        prompt_end = ACPUpdateEvent(
            event_type="prompt_end",
            timestamp=datetime.now(UTC),
            payload={"session_id": "session-123"},
            correlation_id="prompt-123",
        )
        await accumulator.receive_update(prompt_end)

        # The renderer should have emitted the final answer with accumulated chunks
        all_messages = []
        while message_bus.outbound_size > 0:
            all_messages.append(await message_bus.consume_outbound())

        # Find the final answer with accumulated content
        final_answer = None
        for msg in all_messages:
            if msg.metadata.get("update_type") == "final_answer":
                final_answer = msg
                break

        assert final_answer is not None, "No final_answer message found"
        # Should have all 3 parts accumulated
        assert "Part 1" in final_answer.content
        assert "Part 2" in final_answer.content
        assert "Part 3" in final_answer.content


class TestFinalAnswerEmission:
    """Tests for final answer emission."""

    @pytest.fixture
    def message_bus(self):
        return MessageBus()

    @pytest.fixture
    def update_sink(self):
        return FakeUpdateSink()

    @pytest.fixture
    def permission_broker(self):
        return FakePermissionBroker()

    @pytest.mark.asyncio
    async def test_final_answer_coherent_after_chunks(
        self, message_bus, update_sink, permission_broker
    ):
        """Given the final answer arrives after many chunks, when rendering completes,
        then the user receives one coherent completion message."""
        accumulator = ACPUpdateAccumulator(update_sink)
        renderer = ACPRenderer(
            message_bus=message_bus,
            permission_broker=permission_broker,
        )
        accumulator.subscribe(renderer)

        # Simulate prompt start
        prompt_start = ACPUpdateEvent(
            event_type="prompt_start",
            timestamp=datetime.now(UTC),
            payload={"content": "Explain quantum computing"},
            correlation_id="prompt-123",
        )
        await accumulator.receive_update(prompt_start)

        # Simulate multiple chunks
        for i in range(5):
            chunk = ACPStreamChunk(
                type=ACPStreamChunkType.CONTENT_DELTA,
                content=f"Chunk {i + 1} of content. ",
            )
            await accumulator.receive_chunk(chunk, correlation_id="prompt-123")

        # Simulate prompt end - this should trigger final answer
        prompt_end = ACPUpdateEvent(
            event_type="prompt_end",
            timestamp=datetime.now(UTC),
            payload={"session_id": "session-123"},
            correlation_id="prompt-123",
        )
        await accumulator.receive_update(prompt_end)

        # Consume all outbound messages and find the final answer
        all_messages = []
        while message_bus.outbound_size > 0:
            all_messages.append(await message_bus.consume_outbound())

        # Find the final answer message (contains accumulated chunks)
        final_answer = None
        for msg in all_messages:
            if msg.metadata.get("update_type") == "final_answer":
                final_answer = msg
                break

        assert final_answer is not None, "No final_answer message found"
        assert final_answer.content is not None
        # Should contain accumulated content (all 5 chunks joined)
        assert len(final_answer.content) > 50  # Has substantive content


class TestDuplicateSuppression:
    """Tests for duplicate suppression."""

    @pytest.fixture
    def message_bus(self):
        return MessageBus()

    @pytest.fixture
    def update_sink(self):
        return FakeUpdateSink()

    @pytest.fixture
    def permission_broker(self):
        return FakePermissionBroker()

    @pytest.mark.asyncio
    async def test_identical_updates_suppressed(self, message_bus, update_sink, permission_broker):
        """Given redundant or repeated updates arrive, when rendering runs,
        then duplicate outbound spam is suppressed."""
        accumulator = ACPUpdateAccumulator(update_sink)
        renderer = ACPRenderer(
            message_bus=message_bus,
            permission_broker=permission_broker,
        )
        accumulator.subscribe(renderer)

        # Send the same update event multiple times
        same_event = ACPUpdateEvent(
            event_type="tool_use_start",
            timestamp=datetime.now(UTC),
            payload={
                "tool_name": "read",
                "tool_input": {"path": "/home/user/test.txt"},
                "tool_use_id": "tool-123",
            },
            correlation_id="prompt-123",
        )

        # Send it 3 times
        for _ in range(3):
            await accumulator.receive_update(same_event)

        # Should only get ONE outbound message, not 3
        # Drain the queue
        messages = []
        while message_bus.outbound_size > 0:
            messages.append(await message_bus.consume_outbound())

        # Should be at most 1 message (suppression works)
        assert len(messages) <= 1, f"Expected at most 1 message, got {len(messages)}"

    @pytest.mark.asyncio
    async def test_different_updates_not_suppressed(
        self, message_bus, update_sink, permission_broker
    ):
        """Given different updates arrive, when rendering runs,
        then they are all emitted."""
        accumulator = ACPUpdateAccumulator(update_sink)
        renderer = ACPRenderer(
            message_bus=message_bus,
            permission_broker=permission_broker,
        )
        accumulator.subscribe(renderer)

        # Send different update events
        events = [
            ACPUpdateEvent(
                event_type="tool_use_start",
                timestamp=datetime.now(UTC),
                payload={"tool_name": "read", "tool_use_id": "tool-1"},
                correlation_id="prompt-123",
            ),
            ACPUpdateEvent(
                event_type="tool_use_start",
                timestamp=datetime.now(UTC),
                payload={"tool_name": "write", "tool_use_id": "tool-2"},
                correlation_id="prompt-123",
            ),
        ]

        for event in events:
            await accumulator.receive_update(event)

        # Should get 2 messages
        messages = []
        while message_bus.outbound_size > 0:
            messages.append(await message_bus.consume_outbound())

        assert len(messages) == 2


class TestPermissionStateRendering:
    """Tests for permission state rendering from ACP-06."""

    @pytest.fixture
    def message_bus(self):
        return MessageBus()

    @pytest.fixture
    def update_sink(self):
        return FakeUpdateSink()

    @pytest.fixture
    def permission_broker(self):
        return FakePermissionBroker()

    @pytest.mark.asyncio
    async def test_permission_request_renders_progress(
        self, message_bus, update_sink, permission_broker
    ):
        """Given a permission request arrives, when rendering runs,
        then the user sees a permission request message."""
        accumulator = ACPUpdateAccumulator(update_sink)
        renderer = ACPRenderer(
            message_bus=message_bus,
            permission_broker=permission_broker,
        )
        accumulator.subscribe(renderer)

        # Simulate permission request event
        perm_event = ACPUpdateEvent(
            event_type="permission_request",
            timestamp=datetime.now(UTC),
            payload={
                "permission_type": "filesystem",
                "description": "Read file: /home/user/test.txt",
                "resource": "/home/user/test.txt",
                "request_id": "perm-123",
            },
            correlation_id="prompt-123",
        )
        await accumulator.receive_update(perm_event)

        # Should get an outbound message about permission
        outbound = await message_bus.consume_outbound()
        assert "permission" in outbound.content.lower() or " filesystem" in outbound.content.lower()

    @pytest.mark.asyncio
    async def test_permission_decision_renders_result(
        self, message_bus, update_sink, permission_broker
    ):
        """Given a permission decision arrives, when rendering runs,
        then the user sees the decision result."""
        accumulator = ACPUpdateAccumulator(update_sink)
        renderer = ACPRenderer(
            message_bus=message_bus,
            permission_broker=permission_broker,
        )
        accumulator.subscribe(renderer)

        # Simulate permission decision event
        decision_event = ACPUpdateEvent(
            event_type="permission_decision",
            timestamp=datetime.now(UTC),
            payload={
                "request_id": "perm-123",
                "granted": True,
                "reason": "User approved",
            },
            correlation_id="prompt-123",
        )
        await accumulator.receive_update(decision_event)

        outbound = await message_bus.consume_outbound()
        assert outbound.content is not None
        # Should reflect the decision (approved/denied)
        assert "approved" in outbound.content.lower() or "granted" in outbound.content.lower()


class TestIntegrationWithFakeAgent:
    """Tests for integration with fake agent fixtures."""

    @pytest.fixture
    def message_bus(self):
        return MessageBus()

    @pytest.mark.asyncio
    async def test_full_prompt_flow_renders_correctly(self, message_bus):
        """Given a full prompt flow with fake agent, when it completes,
        then the rendering produces correct outbound messages."""
        # Create fake agent with update sink that feeds into our rendering
        from tests.acp.fakes import FakeACPAgentRuntime, FakeACPSessionStore

        session_store = FakeACPSessionStore()
        permission_broker = FakePermissionBroker()

        # Create accumulator and renderer
        accumulator = ACPUpdateAccumulator()
        renderer = ACPRenderer(
            message_bus=message_bus,
            permission_broker=permission_broker,
        )
        accumulator.subscribe(renderer)

        # Create a direct update sink that forwards to the accumulator
        direct_sink = ACPDirectUpdateSink(accumulator)

        fake_runtime = FakeACPAgentRuntime(
            session_store=session_store,
            update_sinks=[direct_sink],
        )

        # Initialize
        from nanobot.acp.types import ACPInitializeRequest

        await fake_runtime.initialize(ACPInitializeRequest(session_id="test-session"))

        # Send a prompt
        from nanobot.acp.types import ACPPromptRequest

        await fake_runtime.prompt(
            ACPPromptRequest(content="Hello, world!", session_id="test-session")
        )

        # Should have received outbound messages from the rendering
        # (at least the final answer)
        assert message_bus.outbound_size >= 1
