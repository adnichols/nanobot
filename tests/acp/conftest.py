"""Pytest fixtures for ACP testing.

These fixtures provide fake ACP agent implementations that simulate
initialize, prompt, session updates, permission requests, cancel,
and load-session flows for testing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nanobot.acp.types import (
    ACPCancelRequest,
    ACPFilesystemCallback,
    ACPInitializeRequest,
    ACPLoadSessionRequest,
    ACPPermissionDecision,
    ACPPermissionRequest,
    ACPPromptRequest,
    ACPSessionRecord,
    ACPTerminalCallback,
)
from tests.acp.fakes import (
    FakeACPAgentRuntime,
    FakeACPCallbackRegistry,
    FakeACPSessionStore,
    FakeACPUpdateSink,
)


@pytest.fixture
def fake_session_store():
    """Provide a fake session store."""
    return FakeACPSessionStore()


@pytest.fixture
def fake_callback_registry():
    """Provide a fake callback registry."""
    return FakeACPCallbackRegistry()


@pytest.fixture
def fake_update_sink():
    """Provide a fake update sink."""
    return FakeACPUpdateSink()


@pytest.fixture
def fake_agent_runtime(
    fake_session_store,
    fake_callback_registry,
    fake_update_sink,
):
    """Provide a fully configured fake ACP agent runtime."""
    runtime = FakeACPAgentRuntime(
        session_store=fake_session_store,
        callback_registry=fake_callback_registry,
        update_sinks=[fake_update_sink],
    )
    return runtime


@pytest.fixture
def sample_session_record():
    """Provide a sample session record for testing."""
    return ACPSessionRecord(
        id="test-session-123",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        state={"counter": 0},
        messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        active_tool_use_id=None,
        metadata={"model": "test-model"},
    )


@pytest.fixture
def sample_initialize_request():
    """Provide a sample initialize request."""
    return ACPInitializeRequest(
        session_id="test-session-123",
        system_prompt="You are a helpful assistant.",
        tools=[],
        model="test-model",
    )


@pytest.fixture
def sample_prompt_request():
    """Provide a sample prompt request."""
    return ACPPromptRequest(
        content="What is the capital of France?",
        session_id="test-session-123",
    )


@pytest.fixture
def sample_cancel_request():
    """Provide a sample cancel request."""
    return ACPCancelRequest(
        session_id="test-session-123",
        operation_id="op-123",
    )


@pytest.fixture
def sample_load_session_request():
    """Provide a sample load session request."""
    return ACPLoadSessionRequest(
        session_id="test-session-123",
    )


@pytest.fixture
def sample_filesystem_callback():
    """Provide a sample filesystem callback."""
    return ACPFilesystemCallback(
        operation="read",
        path="/home/user/test.txt",
        content=None,
        metadata={},
    )


@pytest.fixture
def sample_terminal_callback():
    """Provide a sample terminal callback."""
    return ACPTerminalCallback(
        command="ls -la /home/user",
        working_directory="/home/user",
        environment={"HOME": "/home/user"},
        timeout=30.0,
    )


@pytest.fixture
def sample_permission_request(sample_filesystem_callback):
    """Provide a sample permission request."""
    return ACPPermissionRequest(
        id="perm-123",
        permission_type="filesystem",
        description="Read file: /home/user/test.txt",
        resource="/home/user/test.txt",
        callback=sample_filesystem_callback,
        correlation_id="corr-123",
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def sample_permission_decision():
    """Provide a sample permission decision."""
    return ACPPermissionDecision(
        request_id="perm-123",
        granted=True,
        reason="User approved",
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
async def initialized_agent(fake_agent_runtime, sample_initialize_request):
    """Provide an initialized fake agent runtime."""
    await fake_agent_runtime.initialize(sample_initialize_request)
    return fake_agent_runtime
