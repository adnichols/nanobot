"""Tests for fake ACP agent behavior.

These tests verify that the fake ACP agent harness properly simulates
the agent protocol behaviors needed for testing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nanobot.acp.types import (
    ACPFilesystemCallback,
    ACPPermissionDecision,
    ACPSessionRecord,
    ACPStreamChunk,
    ACPStreamChunkType,
    ACPTerminalCallback,
)


class TestFakeAgentInitialization:
    """Tests for fake agent initialization behavior."""

    @pytest.mark.asyncio
    async def test_initialize_sets_initialized_flag(
        self, fake_agent_runtime, sample_initialize_request
    ):
        """Initialize should set the initialized flag."""
        assert fake_agent_runtime._initialized is False
        await fake_agent_runtime.initialize(sample_initialize_request)
        assert fake_agent_runtime._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_requires_session_id(
        self, fake_agent_runtime, sample_initialize_request
    ):
        """Initialize should store the session ID."""
        await fake_agent_runtime.initialize(sample_initialize_request)
        assert fake_agent_runtime._current_session_id == sample_initialize_request.session_id

    @pytest.mark.asyncio
    async def test_initialize_emits_event(self, fake_agent_runtime, sample_initialize_request):
        """Initialize should emit an initialize event."""
        await fake_agent_runtime.initialize(sample_initialize_request)
        sink = fake_agent_runtime.update_sinks[0]
        assert len(sink.updates) == 1
        assert sink.updates[0].event_type == "initialize"


class TestFakeAgentPrompt:
    """Tests for fake agent prompt behavior."""

    @pytest.mark.asyncio
    async def test_load_session_fails_without_store(
        self, fake_callback_registry, fake_update_sink, sample_load_session_request
    ):
        """Load session should fail if no session store is configured."""
        # Create runtime without session store
        from tests.acp.fakes import FakeACPAgentRuntime

        runtime_without_store = FakeACPAgentRuntime(
            session_store=None,
            callback_registry=fake_callback_registry,
            update_sinks=[fake_update_sink],
        )
        with pytest.raises(NotImplementedError):
            await runtime_without_store.load_session(sample_load_session_request)

    @pytest.mark.asyncio
    async def test_load_session_returns_dict(
        self,
        fake_agent_runtime,
        fake_session_store,
        sample_session_record,
        sample_load_session_request,
    ):
        """Load session should return a dict with status and session."""
        await fake_session_store.save(sample_session_record)
        fake_agent_runtime.session_store = fake_session_store

        result = await fake_agent_runtime.load_session(sample_load_session_request)
        assert isinstance(result, dict)
        assert result["status"] == "loaded"
        assert "session" in result

    @pytest.mark.asyncio
    async def test_load_session_sets_initialized(
        self,
        fake_agent_runtime,
        fake_session_store,
        sample_session_record,
        sample_load_session_request,
    ):
        """Load session should set the initialized flag."""
        await fake_session_store.save(sample_session_record)
        fake_agent_runtime.session_store = fake_session_store

        assert fake_agent_runtime._initialized is False
        await fake_agent_runtime.load_session(sample_load_session_request)
        assert fake_agent_runtime._initialized is True

    @pytest.mark.asyncio
    async def test_load_session_emits_event(
        self,
        fake_agent_runtime,
        fake_session_store,
        sample_session_record,
        sample_load_session_request,
    ):
        """Load session should emit a session_loaded event."""
        await fake_session_store.save(sample_session_record)
        fake_agent_runtime.session_store = fake_session_store

        await fake_agent_runtime.load_session(sample_load_session_request)
        sink = fake_agent_runtime.update_sinks[0]
        assert any(e.event_type == "session_loaded" for e in sink.updates)

    @pytest.mark.asyncio
    async def test_load_session_not_found(
        self, fake_agent_runtime, fake_session_store, sample_load_session_request
    ):
        """Load session should raise if session is not found."""
        fake_agent_runtime.session_store = fake_session_store
        with pytest.raises(ValueError, match="Session not found"):
            await fake_agent_runtime.load_session(sample_load_session_request)


class TestFakeSessionStore:
    """Tests for fake session store behavior."""

    @pytest.mark.asyncio
    async def test_save_and_load(self, fake_session_store, sample_session_record):
        """Should be able to save and load a session."""
        await fake_session_store.save(sample_session_record)
        loaded = await fake_session_store.load(sample_session_record.id)
        assert loaded is not None
        assert loaded.id == sample_session_record.id
        assert loaded.state == sample_session_record.state

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, fake_session_store):
        """Loading nonexistent session should return None."""
        loaded = await fake_session_store.load("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete(self, fake_session_store, sample_session_record):
        """Should be able to delete a session."""
        await fake_session_store.save(sample_session_record)
        await fake_session_store.delete(sample_session_record.id)
        loaded = await fake_session_store.load(sample_session_record.id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, fake_session_store, sample_session_record):
        """Should be able to list all sessions."""
        await fake_session_store.save(sample_session_record)
        sessions = await fake_session_store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == sample_session_record.id


class TestFakeCallbackRegistry:
    """Tests for fake callback registry behavior."""

    @pytest.mark.asyncio
    async def test_register_filesystem_handler(self, fake_callback_registry):
        """Should be able to register a filesystem handler."""

        async def handler(callback):
            return ACPPermissionDecision(request_id="test", granted=True)

        fake_callback_registry.register_filesystem_callback(handler)
        # Handler is registered - would be called in handle_permission_request

    @pytest.mark.asyncio
    async def test_register_terminal_handler(self, fake_callback_registry):
        """Should be able to register a terminal handler."""

        async def handler(callback):
            return ACPPermissionDecision(request_id="test", granted=True)

        fake_callback_registry.register_terminal_callback(handler)

    @pytest.mark.asyncio
    async def test_handle_permission_no_handler(
        self, fake_callback_registry, sample_permission_request
    ):
        """handle_permission_request should return a deterministic denial if no handler is registered."""
        result = await fake_callback_registry.handle_permission_request(sample_permission_request)

        assert result.granted is False
        assert result.request_id == sample_permission_request.id
        assert result.reason == "No handler registered for permission type"


class TestFakeUpdateSink:
    """Tests for fake update sink behavior."""

    @pytest.mark.asyncio
    async def test_send_update(self, fake_update_sink):
        """Should be able to send update events."""
        from nanobot.acp.types import ACPUpdateEvent

        event = ACPUpdateEvent(
            event_type="test",
            timestamp=datetime.now(UTC),
            payload={},
        )
        await fake_update_sink.send_update(event)
        assert len(fake_update_sink.updates) == 1

    @pytest.mark.asyncio
    async def test_send_rendered(self, fake_update_sink):
        """Should be able to send rendered updates."""
        from nanobot.acp.types import ACPRenderedUpdate

        update = ACPRenderedUpdate(
            update_type="text",
            content="Hello",
            metadata={},
        )
        await fake_update_sink.send_rendered(update)
        assert len(fake_update_sink.rendered) == 1

    @pytest.mark.asyncio
    async def test_stream_chunk(self, fake_update_sink):
        """Should be able to stream chunks."""
        chunk = ACPStreamChunk(type=ACPStreamChunkType.CONTENT_DELTA, content="test")
        await fake_update_sink.stream_chunk(chunk)
        assert len(fake_update_sink.stream_chunks) == 1


class TestDownstreamConsumerImport:
    """Tests that verify downstream tracks can import from contract modules."""

    def test_import_from_nanobot_acp_types(self):
        """Should be able to import types from nanobot.acp.types."""
        from nanobot.acp.types import (
            ACPRenderedUpdate,
            ACPStreamChunk,
            ACPUpdateEvent,
        )

        assert ACPSessionRecord is not None
        assert ACPUpdateEvent is not None
        assert ACPRenderedUpdate is not None
        assert ACPFilesystemCallback is not None
        assert ACPTerminalCallback is not None
        assert ACPStreamChunk is not None

    def test_import_from_nanobot_acp_interfaces(self):
        """Should be able to import interfaces from nanobot.acp.interfaces."""
        from nanobot.acp.interfaces import (
            ACPCallbackRegistry,
            ACPRenderEvent,
            ACPSessionStore,
            ACPUpdateSink,
        )

        assert ACPSessionStore is not None
        assert ACPCallbackRegistry is not None
        assert ACPUpdateSink is not None
        assert ACPRenderEvent is not None

    def test_import_from_nanobot_acp_contracts(self):
        """Should be able to import contracts from nanobot.acp.contracts."""
        from nanobot.acp.contracts import (
            ACPContract,
            ACPContractViolation,
        )

        assert ACPContract is not None
        assert ACPContractViolation is not None

    def test_import_from_nanobot_acp(self):
        """Should be able to import everything from nanobot.acp."""
        from nanobot import acp

        assert acp.ACPSessionRecord is not None
        assert acp.ACPSessionStore is not None
        assert acp.ACPContract is not None
