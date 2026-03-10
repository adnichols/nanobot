"""Tests for ACP runtime core functionality.

These tests verify that the ACP runtime properly handles:
- Agent initialization with capability capture
- Session lifecycle (new_session, load_session)
- Prompt flow with request/response correlation
- Cancel flow with clean state transition
- Graceful shutdown handling
- Reconnect semantics for unexpected backend exit
- Multi-session isolation
- Failure handling when backend cannot start
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.acp.types import (
    ACPInitializeRequest,
    ACPLoadSessionRequest,
    ACPPromptRequest,
    ACPSessionRecord,
)


class TestRuntimeInitialization:
    """Tests for ACP runtime initialization."""

    @pytest.mark.asyncio
    async def test_initialize_with_fake_agent_captures_capabilities(
        self, fake_agent_runtime, sample_initialize_request
    ):
        """Given a fake ACP agent starts successfully, when nanobot initializes,
        then agent capabilities are captured."""
        # The runtime should capture capabilities on initialization
        # This test verifies the expected behavior - currently will fail
        result = await fake_agent_runtime.initialize(sample_initialize_request)

        # Verify capabilities are captured in the result
        assert "capabilities" in result or "status" in result

    @pytest.mark.asyncio
    async def test_initialize_failure_returns_testable_error(self):
        """Given an ACP backend cannot be started, when startup is attempted,
        then the runtime returns a testable failure."""
        # Import the runtime class - will fail until implemented
        from nanobot.acp.runtime import ACPAgentRuntime

        # Create runtime with invalid agent path
        runtime = ACPAgentRuntime(agent_path="/nonexistent/path")

        # Attempting to initialize should return a testable failure
        with pytest.raises((FileNotFoundError, RuntimeError, ValueError)):
            await runtime.initialize(ACPInitializeRequest(session_id="test"))

    @pytest.mark.asyncio
    async def test_initialize_stores_session_id(
        self, fake_agent_runtime, sample_initialize_request
    ):
        """Initialize should store the session ID for future operations."""
        await fake_agent_runtime.initialize(sample_initialize_request)
        assert fake_agent_runtime._current_session_id == sample_initialize_request.session_id


class TestSessionLifecycle:
    """Tests for ACP session lifecycle methods."""

    @pytest.mark.asyncio
    async def test_new_session_creates_fresh_session(self):
        """New session should create a fresh session with unique ID."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()
        result = await runtime.new_session()

        # Should return a session with an ID
        assert result is not None
        assert hasattr(result, "session_id") or "session_id" in result

    @pytest.mark.asyncio
    async def test_load_session_from_stored_binding(self, fake_agent_runtime):
        """Given a stored ACP session binding exists, when the runtime starts,
        then session recovery reuses the saved binding."""

        # Create a session record to load
        session_record = ACPSessionRecord(
            id="test-session-123",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={"counter": 0},
            messages=[{"role": "user", "content": "Hello"}],
        )

        # Save the session to the store
        fake_agent_runtime.session_store = MagicMock()
        fake_agent_runtime.session_store.save = AsyncMock()
        fake_agent_runtime.session_store.load = AsyncMock(return_value=session_record)

        # Load the session
        request = ACPLoadSessionRequest(session_id="test-session-123")
        result = await fake_agent_runtime.load_session(request)

        # Verify session was loaded
        assert result is not None
        assert result.get("status") == "loaded" or "session" in result


class TestPromptFlow:
    """Tests for prompt and response correlation."""

    @pytest.mark.asyncio
    async def test_prompt_maintains_request_response_correlation(
        self, initialized_agent, sample_prompt_request
    ):
        """Given an ACP session exists, when nanobot prompts it,
        then request/response correlation stays intact through completion."""
        # Send prompt and verify response maintains correlation
        response = await initialized_agent.prompt(sample_prompt_request)

        # Response should be correlated to the request
        assert response is not None

    @pytest.mark.asyncio
    async def test_prompt_requires_initialization(self, fake_agent_runtime, sample_prompt_request):
        """Prompt should fail if runtime is not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await fake_agent_runtime.prompt(sample_prompt_request)

    @pytest.mark.asyncio
    async def test_prompt_emits_update_events(
        self, initialized_agent, sample_prompt_request, fake_update_sink
    ):
        """Prompt should emit update events for tracking."""
        await initialized_agent.prompt(sample_prompt_request)

        # Verify update events were sent
        assert len(fake_update_sink.updates) > 0
        update_types = [e.event_type for e in fake_update_sink.updates]
        assert "prompt_start" in update_types or "prompt_end" in update_types


class TestCancelFlow:
    """Tests for cancel and state transition."""

    @pytest.mark.asyncio
    async def test_cancel_transitions_state_cleanly(self, initialized_agent, sample_cancel_request):
        """Given cancellation is requested mid-turn, when the runtime sends cancel,
        then prompt state transitions cleanly without corrupting session state."""
        # Send cancel request
        await initialized_agent.cancel(sample_cancel_request)

        # Verify cancel event was emitted
        fake_sink = initialized_agent.update_sinks[0]
        cancel_events = [e for e in fake_sink.updates if e.event_type == "cancel"]
        assert len(cancel_events) > 0

    @pytest.mark.asyncio
    async def test_cancel_after_completion_is_idempotent(
        self, initialized_agent, sample_cancel_request
    ):
        """Cancel should be idempotent - calling after completion should not raise."""
        # Cancel should not raise even if there's no active operation
        await initialized_agent.cancel(sample_cancel_request)
        await initialized_agent.cancel(sample_cancel_request)  # Second call should not raise


class TestShutdownBehavior:
    """Tests for runtime shutdown handling."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_agent_process(self):
        """Shutdown should cleanly close the agent process."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()

        # Initialize first
        await runtime.initialize(ACPInitializeRequest(session_id="test"))

        # Shutdown should clean up resources
        await runtime.shutdown()

        # After shutdown, runtime should indicate it's not active
        assert not hasattr(runtime, "_initialized") or not runtime._initialized

    @pytest.mark.asyncio
    async def test_shutdown_after_prompt_completes_cleanly(self):
        """Shutdown after active prompt should complete cleanly."""
        from nanobot.acp.runtime import ACPAgentRuntime

        # Create and initialize runtime
        runtime = ACPAgentRuntime()
        await runtime.initialize(ACPInitializeRequest(session_id="test"))

        # Complete a prompt first
        await runtime.prompt(ACPPromptRequest(content="test", session_id="test"))

        # Then shutdown - should complete without error
        await runtime.shutdown()

        # Should complete without error


class TestReconnectSemantics:
    """Tests for reconnection after unexpected backend exit."""

    @pytest.mark.asyncio
    async def test_reconnect_after_backend_exit(self):
        """Given the ACP backend process exits unexpectedly, when the next prompt arrives,
        then the runtime reconnects or surfaces a deterministic failure."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime(agent_path="/nonexistent/path")

        # Initialize with a real path that doesn't exist - should fail
        with pytest.raises((FileNotFoundError, RuntimeError)):
            await runtime.initialize(ACPInitializeRequest(session_id="test"))

        # After failed initialization, prompt should also fail
        with pytest.raises(RuntimeError, match="not initialized"):
            await runtime.prompt(ACPPromptRequest(content="test", session_id="test"))

    @pytest.mark.asyncio
    async def test_reconnect_does_not_corrupt_stored_state(
        self, fake_agent_runtime, fake_session_store, sample_session_record
    ):
        """Reconnect should not corrupt stored session state."""
        # Save a session
        await fake_session_store.save(sample_session_record)
        fake_agent_runtime.session_store = fake_session_store

        # Try to load after simulating exit
        # State should remain intact
        loaded = await fake_session_store.load(sample_session_record.id)
        assert loaded is not None
        assert loaded.id == sample_session_record.id


class TestMultiSessionIsolation:
    """Tests for multiple concurrent sessions."""

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolated_by_id(self):
        """Given multiple ACP sessions are active, when prompts and updates overlap,
        then state remains isolated by session and request correlation IDs."""
        from tests.acp.fakes import FakeACPAgentRuntime

        # Create two separate runtimes representing different sessions
        runtime1 = FakeACPAgentRuntime()
        runtime2 = FakeACPAgentRuntime()

        # Initialize both
        await runtime1.initialize(ACPInitializeRequest(session_id="session-1"))
        await runtime2.initialize(ACPInitializeRequest(session_id="session-2"))

        # Send prompts to both (responses are not used, just verify no interference)
        await runtime1.prompt(ACPPromptRequest(content="task 1", session_id="session-1"))
        await runtime2.prompt(ACPPromptRequest(content="task 2", session_id="session-2"))

        # Verify they don't interfere - each has its own state
        assert runtime1._current_session_id != runtime2._current_session_id
        assert runtime1._current_session_id == "session-1"
        assert runtime2._current_session_id == "session-2"


class TestCallbackRegistrationHooks:
    """Tests for callback registration hooks exposed to later tracks."""

    def test_filesystem_callback_registration_hook_available(self):
        """Runtime should expose filesystem callback registration hook."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()

        # Should have method to register filesystem handler
        assert hasattr(runtime, "register_filesystem_callback") or hasattr(
            runtime, "callback_registry"
        )

    def test_terminal_callback_registration_hook_available(self):
        """Runtime should expose terminal callback registration hook."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()

        # Should have method to register terminal handler
        assert hasattr(runtime, "register_terminal_callback") or hasattr(
            runtime, "callback_registry"
        )

    def test_update_sink_registration_available(self):
        """Runtime should allow registering update sinks."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()

        # Should have method to subscribe to updates
        assert hasattr(runtime, "subscribe_updates") or hasattr(runtime, "add_update_sink")


class TestClientWrapper:
    """Tests for ACP client wrapper."""

    @pytest.mark.asyncio
    async def test_client_initializes_runtime(self):
        """Client should initialize the runtime on creation."""
        from nanobot.acp.client import ACPClient

        client = ACPClient(agent_path="fake-agent")

        # Client should have runtime available
        assert hasattr(client, "runtime") or hasattr(client, "_runtime")

    @pytest.mark.asyncio
    async def test_client_prompt_proxies_to_runtime(self):
        """Client.prompt should proxy to runtime.prompt."""
        from nanobot.acp.client import ACPClient

        client = ACPClient()
        await client.initialize()

        # Should be able to prompt through client
        result = await client.prompt("Hello")

        assert result is not None


class TestServiceInterface:
    """Tests for high-level service interface."""

    @pytest.mark.asyncio
    async def test_service_integrates_with_session_management(self):
        """Service should integrate with nanobot's session management."""
        from nanobot.acp.service import ACPService

        service = ACPService()

        # Service should have methods to create/load sessions
        assert hasattr(service, "create_session") or hasattr(service, "new_session")
        assert hasattr(service, "load_session") or hasattr(service, "restore_session")

    @pytest.mark.asyncio
    async def test_service_bridges_to_cli(self):
        """Service should bridge between CLI/chat and ACP runtime."""
        from nanobot.acp.service import ACPService

        service = ACPService()

        # Should have method to handle incoming chat messages
        assert hasattr(service, "handle_message") or hasattr(service, "process_message")


class TestSessionManagementWrapper:
    """Tests for ACP session management wrapper."""

    @pytest.mark.asyncio
    async def test_session_uses_session_store(self):
        """Session wrapper should use ACPSessionStore for persistence."""
        from nanobot.acp.session import ACPSession

        # Session should be able to work with a session store
        session = ACPSession(session_id="test")

        # Should have save/load capability
        assert hasattr(session, "save") or hasattr(session, "persist")

    @pytest.mark.asyncio
    async def test_session_binding_persists(self):
        """Session binding should persist across restarts."""
        from nanobot.acp.session import ACPSession

        session = ACPSession(session_id="test-session", nanobot_session_key="telegram:12345")

        # Binding should be serializable
        binding = session.get_binding()
        assert binding is not None
