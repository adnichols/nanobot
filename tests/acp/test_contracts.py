"""Contract tests for ACP runtime behavior.

These tests verify that the ACP runtime satisfies the contract behaviors
defined in nanobot/acp/contracts.py. Tests are designed to fail initially
until real implementations are added.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from nanobot.acp.contracts import (
    verify_cancel_contract,
    verify_filesystem_callback_contract,
    verify_initialize_contract,
    verify_load_session_contract,
    verify_permission_correlation_contract,
    verify_prompt_streaming_contract,
    verify_session_persistence_contract,
    verify_terminal_callback_contract,
    verify_update_events_contract,
)
from nanobot.acp.types import (
    ACPPromptRequest,
    ACPUpdateEvent,
)


class TestInitializeContract:
    """Tests for the initialize contract."""

    @pytest.mark.asyncio
    async def test_initialize_returns_dict(self, fake_agent_runtime, sample_initialize_request):
        """Initialize should return a dict with status information."""
        result = await verify_initialize_contract(fake_agent_runtime, sample_initialize_request)
        assert result is True

    @pytest.mark.asyncio
    async def test_initialize_emits_event(self, fake_agent_runtime, sample_initialize_request):
        """Initialize should emit an initialization event."""
        await fake_agent_runtime.initialize(sample_initialize_request)
        assert len(fake_agent_runtime.update_sinks[0].updates) > 0
        event = fake_agent_runtime.update_sinks[0].updates[0]
        assert event.event_type == "initialize"


class TestPromptStreamingContract:
    """Tests for the prompt streaming contract."""

    @pytest.mark.asyncio
    async def test_prompt_returns_chunks(self, initialized_agent, sample_prompt_request):
        """Prompt should return stream chunks."""
        result = await verify_prompt_streaming_contract(initialized_agent, sample_prompt_request)
        assert result is True

    @pytest.mark.asyncio
    async def test_prompt_streams_content(self, initialized_agent, sample_prompt_request):
        """Prompt should stream content chunks to sinks."""
        chunks = await initialized_agent.prompt(sample_prompt_request)
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_prompt_emits_start_end_events(self, initialized_agent, sample_prompt_request):
        """Prompt should emit start and end events."""
        await initialized_agent.prompt(sample_prompt_request)
        updates = initialized_agent.update_sinks[0].updates
        event_types = [e.event_type for e in updates]
        assert "prompt_start" in event_types
        assert "prompt_end" in event_types


class TestPermissionCorrelationContract:
    """Tests for permission request/response correlation."""

    @pytest.mark.asyncio
    async def test_permission_request_has_id(self, sample_permission_request):
        """Permission requests should have unique IDs."""
        assert sample_permission_request.id is not None
        assert len(sample_permission_request.id) > 0

    @pytest.mark.asyncio
    async def test_permission_correlation_id_preserved(
        self, fake_agent_runtime, sample_permission_request
    ):
        """Permission decisions should preserve request correlation IDs."""
        result = await verify_permission_correlation_contract(
            fake_agent_runtime, sample_permission_request
        )
        assert result is True


class TestFilesystemCallbackShape:
    """Tests for filesystem callback shape."""

    @pytest.mark.asyncio
    async def test_filesystem_callback_has_operation(self, sample_filesystem_callback):
        """Filesystem callbacks should have an operation field."""
        assert hasattr(sample_filesystem_callback, "operation")
        assert sample_filesystem_callback.operation in ["read", "write", "delete", "list"]

    @pytest.mark.asyncio
    async def test_filesystem_callback_has_path(self, sample_filesystem_callback):
        """Filesystem callbacks should have a path field."""
        assert hasattr(sample_filesystem_callback, "path")
        assert sample_filesystem_callback.path is not None

    @pytest.mark.asyncio
    async def test_filesystem_callback_contract(self, fake_agent_runtime):
        """Filesystem callback contract should be verifiable."""
        result = await verify_filesystem_callback_contract(fake_agent_runtime)
        assert result is True


class TestTerminalCallbackShape:
    """Tests for terminal callback shape."""

    @pytest.mark.asyncio
    async def test_terminal_callback_has_command(self, sample_terminal_callback):
        """Terminal callbacks should have a command field."""
        assert hasattr(sample_terminal_callback, "command")
        assert sample_terminal_callback.command is not None

    @pytest.mark.asyncio
    async def test_terminal_callback_has_working_directory(self, sample_terminal_callback):
        """Terminal callbacks may have a working directory."""
        assert hasattr(sample_terminal_callback, "working_directory")

    @pytest.mark.asyncio
    async def test_terminal_callback_contract(self, fake_agent_runtime):
        """Terminal callback contract should be verifiable."""
        result = await verify_terminal_callback_contract(fake_agent_runtime)
        assert result is True


class TestUpdateEventShapes:
    """Tests for update event shapes."""

    @pytest.mark.asyncio
    async def test_update_event_has_type(self):
        """Update events should have an event_type field."""
        event = ACPUpdateEvent(
            event_type="test_event",
            timestamp=datetime.now(UTC),
            payload={"key": "value"},
        )
        assert event.event_type == "test_event"

    @pytest.mark.asyncio
    async def test_update_event_has_timestamp(self):
        """Update events should have a timestamp field."""
        event = ACPUpdateEvent(
            event_type="test_event",
            timestamp=datetime.now(UTC),
            payload={},
        )
        assert event.timestamp is not None

    @pytest.mark.asyncio
    async def test_update_event_has_payload(self):
        """Update events should have a payload field."""
        event = ACPUpdateEvent(
            event_type="test_event",
            timestamp=datetime.now(UTC),
            payload={"key": "value"},
        )
        assert event.payload == {"key": "value"}

    @pytest.mark.asyncio
    async def test_update_event_has_correlation_id(self):
        """Update events may have a correlation_id for request matching."""
        event = ACPUpdateEvent(
            event_type="test_event",
            timestamp=datetime.now(UTC),
            payload={},
            correlation_id="corr-123",
        )
        assert event.correlation_id == "corr-123"


class TestCancelContract:
    """Tests for the cancel contract."""

    @pytest.mark.asyncio
    async def test_cancel_stops_operation(self, initialized_agent, sample_cancel_request):
        """Cancel should stop the ongoing operation."""
        # Start a prompt in the background
        asyncio.create_task(
            initialized_agent.prompt(
                ACPPromptRequest(content="test", session_id="test-session-123")
            )
        )
        # Give it a moment to start
        await asyncio.sleep(0.01)
        # Cancel
        await verify_cancel_contract(initialized_agent, sample_cancel_request)
        # Operation should be cancelled
        assert initialized_agent._cancelled is True

    @pytest.mark.asyncio
    async def test_cancel_emits_event(self, initialized_agent, sample_cancel_request):
        """Cancel should emit a cancel event."""
        await initialized_agent.cancel(sample_cancel_request)
        updates = initialized_agent.update_sinks[0].updates
        event_types = [e.event_type for e in updates]
        assert "cancel" in event_types


class TestLoadSessionContract:
    """Tests for the load session contract."""

    @pytest.mark.asyncio
    async def test_load_session_requires_store(
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
            await verify_load_session_contract(runtime_without_store, sample_load_session_request)

    @pytest.mark.asyncio
    async def test_load_session_returns_dict(
        self,
        fake_agent_runtime,
        fake_session_store,
        sample_session_record,
        sample_load_session_request,
    ):
        """Load session should return a dict with session data."""
        # Save a session first
        await fake_session_store.save(sample_session_record)
        fake_agent_runtime.session_store = fake_session_store

        result = await verify_load_session_contract(fake_agent_runtime, sample_load_session_request)
        assert result is True

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
        updates = fake_agent_runtime.update_sinks[0].updates
        event_types = [e.event_type for e in updates]
        assert "session_loaded" in event_types

    @pytest.mark.asyncio
    async def test_load_session_not_found(
        self, fake_agent_runtime, fake_session_store, sample_load_session_request
    ):
        """Load session should raise if session not found."""
        fake_agent_runtime.session_store = fake_session_store
        with pytest.raises(ValueError, match="Session not found"):
            await fake_agent_runtime.load_session(sample_load_session_request)


class TestSessionPersistenceContract:
    """Tests for session persistence contract."""

    @pytest.mark.asyncio
    async def test_session_store_has_save_load(self, fake_session_store):
        """Session store should have save and load methods."""
        result = await verify_session_persistence_contract(fake_session_store)
        assert result is True

    @pytest.mark.asyncio
    async def test_save_and_load_session(self, fake_session_store, sample_session_record):
        """Should be able to save and load a session."""
        await fake_session_store.save(sample_session_record)
        loaded = await fake_session_store.load(sample_session_record.id)
        assert loaded is not None
        assert loaded.id == sample_session_record.id

    @pytest.mark.asyncio
    async def test_delete_session(self, fake_session_store, sample_session_record):
        """Should be able to delete a session."""
        await fake_session_store.save(sample_session_record)
        await fake_session_store.delete(sample_session_record.id)
        loaded = await fake_session_store.load(sample_session_record.id)
        assert loaded is None


class TestUpdateEventsContract:
    """Tests for update events contract."""

    @pytest.mark.asyncio
    async def test_update_sink_has_send_update(self, fake_update_sink):
        """Update sink should have a send_update method."""
        result = await verify_update_events_contract(fake_update_sink)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_update_stores_event(self, fake_update_sink):
        """send_update should store the event."""
        event = ACPUpdateEvent(
            event_type="test",
            timestamp=datetime.now(UTC),
            payload={},
        )
        await fake_update_sink.send_update(event)
        assert len(fake_update_sink.updates) == 1
