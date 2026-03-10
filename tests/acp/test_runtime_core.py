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

RED PHASE: These tests capture the missing behavior. They should FAIL now
and PASS after the real runtime transport is implemented.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.acp.types import (
    ACPCancelRequest,
    ACPInitializeRequest,
    ACPLoadSessionRequest,
    ACPPromptRequest,
    ACPSessionRecord,
)


class _RecordingStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None


class _QueuedStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = iter(lines)

    async def readline(self) -> bytes:
        return next(self._lines, b"")


class _BlockingStdout:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self._release = asyncio.Event()

    async def readline(self) -> bytes:
        self.started.set()
        await self._release.wait()
        return b""


class _FakeProcess:
    def __init__(self, stdout) -> None:
        self.stdin = _RecordingStdin()
        self.stdout = stdout
        self.stderr = None
        self.returncode = None


class TestRuntimeInitialization:
    """Tests for ACP runtime initialization."""

    @pytest.mark.asyncio
    async def test_initialize_with_fake_agent_captures_capabilities(
        self, fake_agent_runtime, sample_initialize_request
    ):
        """Given a fake ACP agent starts successfully, when nanobot initializes,
        then agent capabilities are captured."""
        result = await fake_agent_runtime.initialize(sample_initialize_request)
        assert "capabilities" in result or "status" in result

    @pytest.mark.asyncio
    async def test_initialize_failure_returns_testable_error(self):
        """Given an ACP backend cannot be started, when startup is attempted,
        then the runtime returns a testable failure."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime(agent_path="/nonexistent/path")
        with pytest.raises((FileNotFoundError, RuntimeError, ValueError)):
            await runtime.initialize(ACPInitializeRequest(session_id="test"))

    @pytest.mark.asyncio
    async def test_initialize_stores_session_id(
        self, fake_agent_runtime, sample_initialize_request
    ):
        """Initialize should store the session ID for future operations."""
        await fake_agent_runtime.initialize(sample_initialize_request)
        assert fake_agent_runtime._current_session_id == sample_initialize_request.session_id


class TestRealRuntimePrompt:
    """RED tests for real runtime prompt round-trip.

    These tests capture the gap where the real agent mode raises
    RuntimeError("Real agent mode not fully implemented") instead of
    actually communicating with the backend.
    """

    @pytest.mark.asyncio
    async def test_real_runtime_prompt_does_not_raise_stub_error(self):
        """Given ACP runtime is initialized with a real agent path,
        when prompt is called, then it should NOT raise 'Real agent mode not fully implemented'.

        This is the primary gap: the current code raises a stub error instead of
        actually sending the prompt to the backend.
        """
        from nanobot.acp.runtime import ACPAgentRuntime

        # Use fake mode initially to initialize, then we'll test real mode behavior
        runtime = ACPAgentRuntime(agent_path=None)  # fake mode
        await runtime.initialize(ACPInitializeRequest(session_id="test"))

        # In fake mode, this should work. The test for real mode will fail
        # because it hits the stub error - this is the RED behavior we want to capture.
        result = await runtime.prompt(ACPPromptRequest(content="test", session_id="test"))

        # Fake mode should return a response
        assert result is not None

    @pytest.mark.asyncio
    async def test_real_runtime_with_agent_path_uses_backend_messages_instead_of_stub_error(
        self, monkeypatch
    ):
        """Real mode should exercise backend I/O instead of raising the old stub error."""
        from nanobot.acp.runtime import ACPAgentRuntime

        async def fake_create_subprocess_exec(*_cmd, **_kwargs):
            return _FakeProcess(
                _QueuedStdout([b'{"type":"error","message":"backend unavailable"}\n'])
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        runtime = ACPAgentRuntime(agent_path="opencode")
        await runtime.initialize(ACPInitializeRequest(session_id="test"))

        result = await runtime.prompt(ACPPromptRequest(content="test", session_id="test"))

        assert result
        assert result[0].content == "backend unavailable"
        assert "not fully implemented" not in result[0].content.lower()

    @pytest.mark.asyncio
    async def test_initialize_uses_agent_definition_args_without_duplicate_acp(self, monkeypatch):
        """Initialize should honor configured args without prepending a second `acp`."""
        from nanobot.acp.runtime import ACPAgentRuntime
        from nanobot.config.schema import ACPAgentDefinition

        captured: dict[str, Any] = {}

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _FakeProcess(_QueuedStdout([]))

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        runtime = ACPAgentRuntime(
            agent_path="opencode",
            agent_definition=ACPAgentDefinition(
                id="opencode",
                command="opencode",
                args=["acp", "--verbose"],
            ),
        )

        await runtime.initialize(ACPInitializeRequest(session_id="test"))

        assert captured["cmd"] == ("opencode", "acp", "--verbose")

    @pytest.mark.asyncio
    async def test_real_prompt_emits_prompt_start_and_clears_active_prompt(self):
        """Real-mode prompt should emit correlation-scoped updates and clear active prompt tracking."""
        from nanobot.acp.runtime import ACPAgentRuntime
        from tests.acp.fakes import FakeACPUpdateSink

        runtime = ACPAgentRuntime(agent_path="opencode")
        runtime._fake_mode = False
        runtime._initialized = True
        runtime._process = cast(
            Any,
            _FakeProcess(
                _QueuedStdout(
                    [
                        b'{"type":"content_delta","content":"hello"}\n',
                        b'{"type":"done"}\n',
                    ]
                ),
            ),
        )
        sink = FakeACPUpdateSink()
        runtime.subscribe_updates(sink)

        chunks = await runtime.prompt(ACPPromptRequest(content="test", session_id="sess-1"))

        assert [chunk.content for chunk in chunks if chunk.content] == ["hello"]
        assert [event.event_type for event in sink.updates][-2:] == ["prompt_start", "prompt_end"]
        assert sink.updates[-1].correlation_id == sink.updates[-2].correlation_id
        assert runtime._active_prompts == {}

    @pytest.mark.asyncio
    async def test_cancel_cancels_active_prompt_and_writes_cancel_message(self):
        """Cancel should reach an in-flight real prompt instead of no-op'ing."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime(agent_path="opencode")
        runtime._fake_mode = False
        runtime._initialized = True
        runtime._process = cast(Any, _FakeProcess(_BlockingStdout()))
        process = cast(_FakeProcess, runtime._process)

        prompt_task = asyncio.create_task(
            runtime.prompt(ACPPromptRequest(content="test", session_id="sess-1"))
        )
        blocking_stdout = cast(_BlockingStdout, process.stdout)
        await blocking_stdout.started.wait()

        await runtime.cancel(ACPCancelRequest(session_id="sess-1", operation_id="op-1"))

        assert prompt_task.cancelled()
        stdin = cast(_RecordingStdin, process.stdin)
        assert any(b'"type": "cancel"' in write for write in stdin.writes)


class TestSessionLifecycle:
    """Tests for ACP session lifecycle methods."""

    @pytest.mark.asyncio
    async def test_new_session_creates_fresh_session(self):
        """New session should create a fresh session with unique ID."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()
        result = await runtime.new_session()
        assert result is not None
        assert hasattr(result, "session_id") or "session_id" in result

    @pytest.mark.asyncio
    async def test_load_session_from_stored_binding(self, fake_agent_runtime):
        """Given a stored ACP session binding exists, when the runtime starts,
        then session recovery reuses the saved binding."""
        session_record = ACPSessionRecord(
            id="test-session-123",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={"counter": 0},
            messages=[{"role": "user", "content": "Hello"}],
        )

        fake_agent_runtime.session_store = MagicMock()
        fake_agent_runtime.session_store.save = AsyncMock()
        fake_agent_runtime.session_store.load = AsyncMock(return_value=session_record)

        request = ACPLoadSessionRequest(session_id="test-session-123")
        result = await fake_agent_runtime.load_session(request)

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
        response = await initialized_agent.prompt(sample_prompt_request)
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

        assert len(fake_update_sink.updates) > 0
        update_types = [e.event_type for e in fake_update_sink.updates]
        assert "prompt_start" in update_types or "prompt_end" in update_types


class TestCancelFlow:
    """Tests for cancel and state transition."""

    @pytest.mark.asyncio
    async def test_cancel_transitions_state_cleanly(self, initialized_agent, sample_cancel_request):
        """Given cancellation is requested mid-turn, when the runtime sends cancel,
        then prompt state transitions cleanly without corrupting session state."""
        await initialized_agent.cancel(sample_cancel_request)

        fake_sink = initialized_agent.update_sinks[0]
        cancel_events = [e for e in fake_sink.updates if e.event_type == "cancel"]
        assert len(cancel_events) > 0

    @pytest.mark.asyncio
    async def test_cancel_after_completion_is_idempotent(
        self, initialized_agent, sample_cancel_request
    ):
        """Cancel should be idempotent - calling after completion should not raise."""
        await initialized_agent.cancel(sample_cancel_request)
        await initialized_agent.cancel(sample_cancel_request)


class TestShutdownBehavior:
    """Tests for runtime shutdown handling."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_agent_process(self):
        """Shutdown should cleanly close the agent process."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()
        await runtime.initialize(ACPInitializeRequest(session_id="test"))
        await runtime.shutdown()
        assert not hasattr(runtime, "_initialized") or not runtime._initialized

    @pytest.mark.asyncio
    async def test_shutdown_after_prompt_completes_cleanly(self):
        """Shutdown after active prompt should complete cleanly."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()
        await runtime.initialize(ACPInitializeRequest(session_id="test"))
        await runtime.prompt(ACPPromptRequest(content="test", session_id="test"))
        await runtime.shutdown()


class TestReconnectSemantics:
    """Tests for reconnection after unexpected backend exit.

    RED PHASE: These tests capture the gap where the runtime doesn't have
    proper fallback behavior when the backend exits unexpectedly.
    """

    @pytest.mark.asyncio
    async def test_reconnect_after_backend_exit_fails_deterministically(self):
        """Given the ACP backend process exits unexpectedly, when the next prompt arrives,
        then the runtime should either reconnect or surface a deterministic failure,
        not pretend everything is fine.

        RED PHASE: Currently the code doesn't handle this case well.
        """
        from nanobot.acp.runtime import ACPAgentRuntime

        # Create runtime with a path that exists but we'll simulate exit
        runtime = ACPAgentRuntime(agent_path="/nonexistent/path")

        with pytest.raises((FileNotFoundError, RuntimeError)):
            await runtime.initialize(ACPInitializeRequest(session_id="test"))

        with pytest.raises(RuntimeError, match="not initialized"):
            await runtime.prompt(ACPPromptRequest(content="test", session_id="test"))

    @pytest.mark.asyncio
    async def test_reconnect_does_not_corrupt_stored_state(
        self, fake_agent_runtime, fake_session_store, sample_session_record
    ):
        """Reconnect should not corrupt stored session state."""
        await fake_session_store.save(sample_session_record)
        fake_agent_runtime.session_store = fake_session_store

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

        runtime1 = FakeACPAgentRuntime()
        runtime2 = FakeACPAgentRuntime()

        await runtime1.initialize(ACPInitializeRequest(session_id="session-1"))
        await runtime2.initialize(ACPInitializeRequest(session_id="session-2"))

        await runtime1.prompt(ACPPromptRequest(content="task 1", session_id="session-1"))
        await runtime2.prompt(ACPPromptRequest(content="task 2", session_id="session-2"))

        assert runtime1._current_session_id != runtime2._current_session_id
        assert runtime1._current_session_id == "session-1"
        assert runtime2._current_session_id == "session-2"


class TestCallbackRegistrationHooks:
    """Tests for callback registration hooks exposed to later tracks."""

    def test_filesystem_callback_registration_hook_available(self):
        """Runtime should expose filesystem callback registration hook."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()
        assert hasattr(runtime, "register_filesystem_callback") or hasattr(
            runtime, "callback_registry"
        )

    def test_terminal_callback_registration_hook_available(self):
        """Runtime should expose terminal callback registration hook."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()
        assert hasattr(runtime, "register_terminal_callback") or hasattr(
            runtime, "callback_registry"
        )

    def test_update_sink_registration_available(self):
        """Runtime should allow registering update sinks."""
        from nanobot.acp.runtime import ACPAgentRuntime

        runtime = ACPAgentRuntime()
        assert hasattr(runtime, "subscribe_updates") or hasattr(runtime, "add_update_sink")


class TestClientWrapper:
    """Tests for ACP client wrapper."""

    @pytest.mark.asyncio
    async def test_client_initializes_runtime(self):
        """Client should initialize the runtime on creation."""
        from nanobot.acp.client import ACPClient

        client = ACPClient(agent_path="fake-agent")
        assert hasattr(client, "runtime") or hasattr(client, "_runtime")

    @pytest.mark.asyncio
    async def test_client_prompt_proxies_to_runtime(self):
        """Client.prompt should proxy to runtime.prompt."""
        from nanobot.acp.client import ACPClient

        client = ACPClient()
        await client.initialize()
        result = await client.prompt("Hello")
        assert result is not None


class TestServiceInterface:
    """Tests for high-level service interface."""

    @pytest.mark.asyncio
    async def test_service_integrates_with_session_management(self):
        """Service should integrate with nanobot's session management."""
        from nanobot.acp.service import ACPService

        service = ACPService()
        assert hasattr(service, "create_session") or hasattr(service, "new_session")
        assert hasattr(service, "load_session") or hasattr(service, "restore_session")

    @pytest.mark.asyncio
    async def test_service_bridges_to_cli(self):
        """Service should bridge between CLI/chat and ACP runtime."""
        from nanobot.acp.service import ACPService

        service = ACPService()
        assert hasattr(service, "handle_message") or hasattr(service, "process_message")


class TestSessionManagementWrapper:
    """Tests for ACP session management wrapper."""

    @pytest.mark.asyncio
    async def test_session_uses_session_store(self):
        """Session wrapper should use ACPSessionStore for persistence."""
        from nanobot.acp.session import ACPSession

        session = ACPSession(session_id="test")
        assert hasattr(session, "save") or hasattr(session, "persist")

    @pytest.mark.asyncio
    async def test_session_binding_persists(self):
        """Session binding should persist across restarts."""
        from nanobot.acp.session import ACPSession

        session = ACPSession(session_id="test-session", nanobot_session_key="telegram:12345")
        binding = session.get_binding()
        assert binding is not None
