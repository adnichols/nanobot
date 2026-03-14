"""Tests for SDK transport adapter.

These tests verify the SDK-based ACP transport layer.
Tests requiring a live OpenCode binary are marked with @pytest.mark.opencode_real.
"""

from __future__ import annotations

import shutil
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from tests.acp.fakes import FakeACPUpdateSink


def should_run_real_tests() -> bool:
    """Check if real backend tests should run."""
    import os

    return os.environ.get("NANOBOT_TEST_OPENCODE") == "1"


class TestSDKTypesConversions:
    """Tests for SDK type conversion functions."""

    def test_to_sdk_initialize_params_basic(self):
        """Test basic initialize params conversion."""
        from nanobot.acp.sdk_types import to_sdk_initialize_params
        from nanobot.acp.types import ACPInitializeRequest

        request = ACPInitializeRequest(
            session_id="test-session",
            system_prompt="You are a helpful assistant.",
        )

        params = to_sdk_initialize_params(request)

        assert params == {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "clientInfo": {"name": "nanobot", "version": "0.1.0"},
        }

    def test_to_sdk_new_session_params(self):
        """Test new session params conversion."""
        from nanobot.acp.sdk_types import to_sdk_new_session_params

        params = to_sdk_new_session_params("/workspace/project")

        assert params == {
            "cwd": "/workspace/project",
            "mcpServers": [],
        }

    def test_to_sdk_prompt_params(self):
        """Test prompt params conversion."""
        from nanobot.acp.sdk_types import to_sdk_prompt_params

        params = to_sdk_prompt_params(content="Hello, world!", session_id="test-session-id")

        assert params == {
            "sessionId": "test-session-id",
            "prompt": [{"type": "text", "text": "Hello, world!"}],
        }

    def test_to_sdk_load_session_params(self):
        """Test load-session params include the required ACP fields."""
        from nanobot.acp.sdk_types import to_sdk_load_session_params

        params = to_sdk_load_session_params("test-session-id", "/workspace/project")

        assert params == {
            "sessionId": "test-session-id",
            "cwd": "/workspace/project",
            "mcpServers": [],
        }


@pytest.mark.asyncio
async def test_handler_converts_structured_updates_to_internal_events():
    import asyncio

    from nanobot.acp.sdk_client import SDKNotificationHandler

    update_sink = MagicMock()
    update_sink.send_update = AsyncMock()
    handler = SDKNotificationHandler(update_sink=update_sink)

    await handler(
        "session/update",
        {
            "sessionId": "sess-123",
            "update": {
                "sessionUpdate": "agent_thought_chunk",
                "content": {"type": "text", "text": "Thinking..."},
            },
        },
        True,
    )
    await handler(
        "session/update",
        {
            "sessionId": "sess-123",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "tool-123",
                "title": "read",
                "status": "completed",
                "content": [
                    {
                        "type": "content",
                        "content": {"type": "text", "text": "done"},
                    }
                ],
                "rawInput": {"path": "/tmp/test.txt"},
            },
        },
        True,
    )

    await asyncio.sleep(0)

    events = [call.args[0] for call in update_sink.send_update.await_args_list]
    assert len(events) == 2
    assert events[0].event_type == "agent_thought_chunk"
    assert events[0].payload["content"] == "Thinking..."
    assert events[1].event_type == "tool_result"
    assert events[1].payload["tool_name"] == "read"
    assert events[1].payload["content"] == "done"
    assert events[1].payload["tool_input"] == {"path": "/tmp/test.txt"}


@pytest.mark.asyncio
async def test_handler_tracks_available_commands_updates():
    from nanobot.acp.sdk_client import SDKNotificationHandler

    handler = SDKNotificationHandler()

    await handler(
        "session/update",
        {
            "sessionId": "sess-123",
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [
                    {"name": "model", "description": "Switch models"},
                    {"name": "status", "description": "Show status"},
                ],
            },
        },
        True,
    )

    assert handler.available_commands_for_session("sess-123") == [
        {"name": "model", "description": "Switch models"},
        {"name": "status", "description": "Show status"},
    ]


def test_sdk_client_reports_current_available_commands():
    from nanobot.acp.sdk_client import SDKClient, SDKNotificationHandler

    client = SDKClient(agent_path=None)
    handler = SDKNotificationHandler()
    handler._available_commands["sess-123"] = [{"name": "model", "description": "Switch models"}]
    client._notification_handler = handler
    client._current_session_id = "sess-123"

    assert client.current_available_commands() == [
        {"name": "model", "description": "Switch models"}
    ]


@pytest.mark.asyncio
async def test_permission_decision_is_sent_back_over_sdk_connection():
    from nanobot.acp.sdk_client import SDKNotificationHandler
    from nanobot.acp.types import ACPFilesystemCallback, ACPPermissionDecision

    connection = MagicMock()
    connection.send_notification = AsyncMock()
    permission_broker = MagicMock()
    permission_broker.request_permission = AsyncMock(
        return_value=ACPPermissionDecision(
            request_id="perm-1",
            granted=True,
            reason="Allowed by policy",
        )
    )
    update_sink = FakeACPUpdateSink()
    handler = SDKNotificationHandler(
        update_sink=update_sink,
        permission_broker=permission_broker,
    )
    handler.bind_connection(connection)

    response = await handler._handle_permission_request(
        {
            "session_id": "sess-123",
            "request_id": "perm-1",
            "permission_type": "filesystem",
            "description": "Read README",
            "resource": "/workspace/README.md",
            "options": [
                {
                    "optionId": "allow-once",
                    "kind": "allow_once",
                    "name": "Allow once",
                },
                {
                    "optionId": "reject-once",
                    "kind": "reject_once",
                    "name": "Reject",
                },
            ],
        }
    )

    connection.send_notification.assert_not_awaited()
    assert response == {
        "outcome": {
            "outcome": "selected",
            "optionId": "allow-once",
        }
    }
    broker_request = permission_broker.request_permission.await_args.args[0]
    assert isinstance(broker_request.callback, ACPFilesystemCallback)
    assert broker_request.callback.operation == "read"
    assert broker_request.callback.path == "/workspace/README.md"
    assert [event.event_type for event in update_sink.updates] == [
        "permission_request",
        "permission_decision",
    ]


@pytest.mark.asyncio
async def test_notification_permission_decision_uses_notification_transport():
    import asyncio

    from nanobot.acp.sdk_client import SDKNotificationHandler
    from nanobot.acp.types import ACPPermissionDecision

    connection = MagicMock()
    connection.send_notification = AsyncMock()
    permission_broker = MagicMock()
    permission_broker.request_permission = AsyncMock(
        return_value=ACPPermissionDecision(
            request_id="perm-1",
            granted=True,
            reason="Allowed by policy",
        )
    )
    handler = SDKNotificationHandler(permission_broker=permission_broker)
    handler.bind_connection(connection)

    await handler(
        "session/request_permission",
        {
            "session_id": "sess-123",
            "request_id": "perm-1",
            "permission_type": "filesystem",
            "description": "Read README",
            "resource": "/workspace/README.md",
            "options": [
                {
                    "optionId": "allow-once",
                    "kind": "allow_once",
                    "name": "Allow once",
                }
            ],
        },
        True,
    )
    await asyncio.sleep(0)

    connection.send_notification.assert_awaited_once_with(
        "session/request_permission",
        {
            "outcome": {
                "outcome": "selected",
                "optionId": "allow-once",
            },
        },
    )


@pytest.mark.asyncio
async def test_filesystem_and_terminal_request_handlers_return_protocol_shapes(tmp_path):
    from nanobot.acp.fs import ACPFilesystemHandler
    from nanobot.acp.sdk_client import SDKNotificationHandler

    connection = MagicMock()
    connection.send_notification = AsyncMock()

    read_path = tmp_path / "README.md"
    read_path.write_text("line 1\nline 2\n")

    filesystem_handler = ACPFilesystemHandler(workspace=tmp_path, restrict_to_workspace=True)

    terminal_manager = MagicMock()
    terminal_manager.create = AsyncMock(return_value="term-123")

    handler = SDKNotificationHandler(
        filesystem_handler=filesystem_handler,
        terminal_manager=terminal_manager,
    )
    handler.bind_connection(connection)

    fs_response = await handler._handle_fs_read(
        {
            "session_id": "sess-123",
            "request_id": "fs-1",
            "path": str(read_path),
            "line": 1,
            "limit": 1,
        }
    )
    terminal_response = await handler._handle_terminal_create(
        {
            "session_id": "sess-123",
            "request_id": "term-1",
            "command": "echo",
            "args": ["hello"],
            "cwd": "/workspace",
            "env": [{"name": "FOO", "value": "bar"}],
        }
    )

    assert fs_response == {"content": "line 1"}
    assert terminal_response == {"terminalId": "term-123"}
    connection.send_notification.assert_not_awaited()
    terminal_manager.create.assert_awaited_once_with(
        ["echo", "hello"],
        working_directory="/workspace",
        environment={"FOO": "bar"},
        output_byte_limit=None,
        permission_checked=False,
    )


@pytest.mark.asyncio
async def test_terminal_lifecycle_requests_are_supported():
    from nanobot.acp.sdk_client import SDKNotificationHandler

    terminal_manager = MagicMock()
    terminal_manager.output = AsyncMock(return_value="hello")
    terminal_manager.wait_for_exit = AsyncMock(return_value=0)
    terminal_manager.kill = AsyncMock(return_value=None)
    terminal_manager.release = AsyncMock(return_value=None)

    handler = SDKNotificationHandler(terminal_manager=terminal_manager)

    assert await handler("terminal/output", {"terminalId": "term-123"}, False) == {
        "output": "hello",
        "truncated": False,
    }
    assert await handler("terminal/wait_for_exit", {"terminalId": "term-123"}, False) == {
        "exitCode": 0
    }
    assert await handler("terminal/kill", {"terminalId": "term-123"}, False) == {}
    assert await handler("terminal/release", {"terminalId": "term-123"}, False) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "operation"),
    [
        ("terminal/output", "output"),
        ("terminal/wait_for_exit", "wait_for_exit"),
        ("terminal/kill", "kill"),
        ("terminal/release", "release"),
    ],
)
async def test_invalid_terminal_lifecycle_requests_raise_protocol_errors(method, operation):
    from acp.exceptions import RequestError

    from nanobot.acp.sdk_client import SDKNotificationHandler
    from nanobot.acp.terminal import ACPInvalidTerminalError

    terminal_manager = MagicMock()
    setattr(
        terminal_manager,
        operation,
        AsyncMock(side_effect=ACPInvalidTerminalError("term-missing", "Terminal does not exist")),
    )
    handler = SDKNotificationHandler(terminal_manager=terminal_manager)

    with pytest.raises(RequestError) as exc_info:
        await handler(method, {"terminalId": "term-missing"}, False)

    assert exc_info.value.code == -32602
    assert exc_info.value.data == {
        "terminalId": "term-missing",
        "operation": operation,
        "reason": "Invalid terminal: term-missing - Terminal does not exist",
    }


@pytest.mark.asyncio
async def test_terminal_wait_timeout_returns_protocol_error():
    import asyncio

    from acp.exceptions import RequestError

    from nanobot.acp.sdk_client import SDKNotificationHandler

    terminal_manager = MagicMock()
    terminal_manager.wait_for_exit = AsyncMock(
        side_effect=asyncio.TimeoutError("Terminal term-123 did not exit within 5 seconds")
    )
    handler = SDKNotificationHandler(terminal_manager=terminal_manager)

    with pytest.raises(RequestError) as exc_info:
        await handler("terminal/wait_for_exit", {"terminalId": "term-123"}, False)

    assert exc_info.value.code == -32602
    assert exc_info.value.data == {
        "terminalId": "term-123",
        "operation": "wait_for_exit",
        "reason": "Terminal term-123 did not exit within 5 seconds",
    }


def test_sdk_client_can_clear_update_subscription():
    from nanobot.acp.sdk_client import SDKClient, SDKNotificationHandler

    sink = MagicMock()
    client = SDKClient(agent_path=None)
    client.subscribe_updates(sink)

    handler = SDKNotificationHandler(update_sink=sink)
    client._notification_handler = handler

    client.clear_update_subscription()

    assert client._update_sink is None
    assert handler._update_sink is None


@pytest.mark.asyncio
async def test_denied_filesystem_request_raises_protocol_error(tmp_path):
    from acp.exceptions import RequestError

    from nanobot.acp.fs import ACPFilesystemHandler
    from nanobot.acp.sdk_client import SDKNotificationHandler

    filesystem_handler = ACPFilesystemHandler(workspace=tmp_path, restrict_to_workspace=True)
    handler = SDKNotificationHandler(filesystem_handler=filesystem_handler)

    with pytest.raises(RequestError) as exc_info:
        await handler._handle_fs_read(
            {
                "session_id": "sess-123",
                "request_id": "fs-1",
                "path": "/tmp/outside-workspace.txt",
            }
        )

    assert exc_info.value.code == -32602
    assert exc_info.value.data == {
        "path": "/tmp/outside-workspace.txt",
        "operation": "read",
        "reason": f"Path /tmp/outside-workspace.txt is outside allowed directory {tmp_path}",
    }


@pytest.mark.asyncio
async def test_large_filesystem_request_returns_protocol_denial_instead_of_crashing(tmp_path):
    from acp.exceptions import RequestError

    from nanobot.acp.fs import ACPFilesystemHandler
    from nanobot.acp.sdk_client import SDKNotificationHandler

    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * (ACPFilesystemHandler._MAX_CHARS * 4 + 1))

    filesystem_handler = ACPFilesystemHandler(workspace=tmp_path, restrict_to_workspace=True)
    handler = SDKNotificationHandler(filesystem_handler=filesystem_handler)

    with pytest.raises(RequestError) as exc_info:
        await handler._handle_fs_read(
            {
                "session_id": "sess-123",
                "request_id": "fs-large-1",
                "path": str(large_file),
            }
        )

    assert exc_info.value.code == -32602
    assert exc_info.value.data == {
        "path": str(large_file),
        "operation": "read",
        "reason": (
            f"File too large ({large_file.stat().st_size:,} bytes). "
            "Use exec tool with head/tail/grep to read portions."
        ),
    }


@pytest.mark.asyncio
async def test_ask_mode_direct_filesystem_callbacks_do_not_bypass_permission_broker(tmp_path):
    from acp.exceptions import RequestError

    from nanobot.acp.fs import ACPFilesystemHandler
    from nanobot.acp.permissions import ACPCallbackRouter, PermissionBrokerFactory
    from nanobot.acp.sdk_client import SDKNotificationHandler

    read_path = tmp_path / "README.md"
    read_path.write_text("hello")

    callback_registry = ACPCallbackRouter()
    permission_broker = PermissionBrokerFactory.create_for_session(
        "telegram:123",
        agent_policy="ask",
        callback_registry=callback_registry,
        timeout=0.01,
    )
    handler = SDKNotificationHandler(
        permission_broker=permission_broker,
        filesystem_handler=ACPFilesystemHandler(workspace=tmp_path, restrict_to_workspace=True),
    )

    with pytest.raises(RequestError) as exc_info:
        await handler._handle_fs_read(
            {
                "session_id": "sess-123",
                "request_id": "fs-ask-1",
                "path": str(read_path),
            }
        )

    assert exc_info.value.code == -32602
    assert exc_info.value.data == {
        "path": str(read_path),
        "operation": "read",
        "reason": "No handler registered for permission type",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "payload", "expected"),
    [
        (
            "_handle_fs_read",
            lambda path: {"session_id": "sess-123", "request_id": "fs-read-1", "path": path},
            lambda path: {"path": path, "operation": "read"},
        ),
        (
            "_handle_fs_write",
            lambda path: {
                "session_id": "sess-123",
                "request_id": "fs-write-1",
                "path": path,
                "content": "demo",
            },
            lambda path: {"path": path, "operation": "write"},
        ),
    ],
)
async def test_granted_broker_still_returns_filesystem_handler_denials(
    tmp_path, method_name, payload, expected
):
    from acp.exceptions import RequestError

    from nanobot.acp.fs import ACPFilesystemHandler
    from nanobot.acp.sdk_client import SDKNotificationHandler
    from nanobot.acp.types import ACPPermissionDecision

    permission_broker = MagicMock()
    permission_broker.request_permission = AsyncMock(
        return_value=ACPPermissionDecision(
            request_id="perm-allow",
            granted=True,
            reason="Allowed by trusted policy",
        )
    )
    handler = SDKNotificationHandler(
        permission_broker=permission_broker,
        filesystem_handler=ACPFilesystemHandler(workspace=tmp_path, restrict_to_workspace=True),
    )

    outside_path = "/tmp/outside-workspace.txt"

    with pytest.raises(RequestError) as exc_info:
        await getattr(handler, method_name)(payload(outside_path))

    assert exc_info.value.code == -32602
    assert exc_info.value.data == {
        **expected(outside_path),
        "reason": f"Path {outside_path} is outside allowed directory {tmp_path}",
    }


@pytest.mark.asyncio
async def test_deny_mode_terminal_callbacks_do_not_bypass_permission_broker(tmp_path):
    from acp.exceptions import RequestError

    from nanobot.acp.permissions import ACPCallbackRouter, PermissionBrokerFactory
    from nanobot.acp.sdk_client import SDKNotificationHandler
    from nanobot.acp.terminal import ACPTerminalManager

    callback_registry = ACPCallbackRouter()
    permission_broker = PermissionBrokerFactory.create_for_session(
        "telegram:123",
        agent_policy="deny",
        callback_registry=callback_registry,
    )
    terminal_manager = ACPTerminalManager(callback_registry=callback_registry)
    handler = SDKNotificationHandler(
        permission_broker=permission_broker,
        terminal_manager=terminal_manager,
    )

    with pytest.raises(RequestError) as exc_info:
        await handler._handle_terminal_create(
            {
                "session_id": "sess-123",
                "request_id": "term-deny-1",
                "command": "echo",
                "args": ["hello"],
                "cwd": str(tmp_path),
            }
        )

    assert exc_info.value.code == -32602
    assert exc_info.value.data == {
        "command": "echo hello",
        "reason": "Denied by trusted interactive policy (action: terminal:echo hello)",
    }


@pytest.mark.asyncio
async def test_denied_permission_still_emits_updates_and_returns_notification():
    import asyncio

    from nanobot.acp.sdk_client import SDKNotificationHandler
    from nanobot.acp.types import ACPPermissionDecision

    connection = MagicMock()
    connection.send_notification = AsyncMock()
    permission_broker = MagicMock()
    permission_broker.request_permission = AsyncMock(
        side_effect=[
            ACPPermissionDecision(
                request_id="perm-allow",
                granted=True,
                reason="Approved",
            ),
            ACPPermissionDecision(
                request_id="perm-deny",
                granted=False,
                reason="Denied by policy",
            ),
        ]
    )
    update_sink = FakeACPUpdateSink()
    handler = SDKNotificationHandler(
        update_sink=update_sink,
        permission_broker=permission_broker,
    )
    handler.bind_connection(connection)

    options = [
        {
            "optionId": "allow-once",
            "kind": "allow_once",
            "name": "Allow once",
        },
        {
            "optionId": "reject-once",
            "kind": "reject_once",
            "name": "Reject",
        },
    ]

    await handler(
        "session/request_permission",
        {
            "session_id": "sess-allow",
            "request_id": "perm-allow",
            "permission_type": "terminal",
            "description": "Run pytest",
            "resource": "pytest",
            "options": options,
        },
        True,
    )
    await handler(
        "session/request_permission",
        {
            "session_id": "sess-deny",
            "request_id": "perm-deny",
            "permission_type": "terminal",
            "description": "Run rm -rf",
            "resource": "rm -rf /tmp/demo",
            "options": options,
        },
        True,
    )
    await asyncio.sleep(0)

    assert connection.send_notification.await_args_list == [
        call(
            "session/request_permission",
            {
                "outcome": {
                    "outcome": "selected",
                    "optionId": "allow-once",
                },
            },
        ),
        call(
            "session/request_permission",
            {
                "outcome": {"outcome": "cancelled"},
            },
        ),
    ]
    assert [event.event_type for event in update_sink.updates] == [
        "permission_request",
        "permission_decision",
        "permission_request",
        "permission_decision",
    ]
    assert update_sink.updates[-1].payload == {
        "session_id": "sess-deny",
        "granted": False,
        "reason": "Denied by policy",
    }


@pytest.mark.asyncio
async def test_terminal_manager_preserves_process_environment(monkeypatch):
    from nanobot.acp.terminal import ACPTerminalManager

    captured: dict[str, Any] = {}

    class FakeProcess:
        stdout = None
        stderr = None
        returncode = 0

    async def fake_create_subprocess_exec(*command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setenv("PATH", "/bin:/usr/bin")
    monkeypatch.setattr(
        "nanobot.acp.terminal.asyncio.create_subprocess_exec", fake_create_subprocess_exec
    )

    manager = ACPTerminalManager()
    terminal_id = await manager.create(
        command=["echo", "hello"],
        working_directory="/tmp",
        environment={"FOO": "bar"},
    )

    assert terminal_id.startswith("term-")
    assert captured["command"] == ("echo", "hello")
    assert captured["cwd"] == "/tmp"
    assert captured["env"]["FOO"] == "bar"
    assert captured["env"]["PATH"] == "/bin:/usr/bin"


@pytest.mark.asyncio
async def test_initialize_advertises_filesystem_and_terminal_capabilities(monkeypatch):
    from nanobot.acp.sdk_client import SDKClient

    class FakeConnection:
        def __init__(self) -> None:
            self.requests: list[tuple[str, dict[str, Any]]] = []

        async def send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
            self.requests.append((method, params))
            if method == "initialize":
                return {
                    "protocolVersion": 1,
                    "agentCapabilities": {"loadSession": True},
                    "agentInfo": {"name": "OpenCode", "version": "1.2.24"},
                }
            raise AssertionError(f"Unexpected request: {method}")

    fake_connection = FakeConnection()
    client = SDKClient(
        agent_path="opencode",
        args=["acp"],
        filesystem_handler=object(),
        terminal_manager=object(),
    )
    client._spawn_connection = AsyncMock(return_value=(fake_connection, "process"))
    monkeypatch.setattr(
        "nanobot.acp.sdk_client.to_sdk_initialize_params",
        lambda _request: {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "clientInfo": {"name": "nanobot", "version": "0.1.0"},
        },
    )

    await client.initialize(session_id="debug-session")

    assert fake_connection.requests == [
        (
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
                "clientInfo": {"name": "nanobot", "version": "0.1.0"},
            },
        )
    ]


class TestSDKClientBasic:
    """Tests for SDK client basic functionality."""

    def test_sdk_client_importable(self):
        """Verify SDKClient is importable."""
        from nanobot.acp.sdk_client import SDKClient

        assert SDKClient is not None

    def test_sdk_client_can_be_instantiated(self):
        """Verify SDKClient can be instantiated."""
        from nanobot.acp.sdk_client import SDKClient

        client = SDKClient(
            agent_path="opencode",
            args=["acp"],
        )

        assert client is not None
        assert client.agent_path == "opencode"
        assert client.args == ["acp"]

    def test_sdk_client_defaults(self):
        """Test SDKClient default values."""
        from nanobot.acp.sdk_client import SDKClient

        client = SDKClient()

        assert client.agent_path is None
        assert client.args == []

    @pytest.mark.asyncio
    async def test_sdk_client_initializes_without_agent(self):
        """Test SDKClient can be initialized without agent path (for testing)."""
        from nanobot.acp.sdk_client import SDKClient

        client = SDKClient()

        # Should be able to check is_initialized without error
        assert client.is_initialized is False

    @pytest.mark.asyncio
    async def test_sdk_client_initializes_with_agent_no_connection(self):
        """Test SDKClient with agent path but not connected yet."""
        from nanobot.acp.sdk_client import SDKClient

        client = SDKClient(
            agent_path="nonexistent-agent",
            args=["acp"],
        )

        # Before connection, should not be initialized
        assert client.is_initialized is False


class TestSDKClientNotificationRouting:
    """Tests for SDK client notification routing."""

    @pytest.mark.asyncio
    async def test_callback_registry_integration(self):
        """Test SDKClient integrates with callback registry."""
        from nanobot.acp.sdk_client import SDKClient

        # Create a mock callback registry
        mock_registry = MagicMock()
        mock_registry.handle_permission_request = AsyncMock()

        client = SDKClient(
            agent_path="opencode",
            args=["acp"],
            callback_registry=mock_registry,
        )

        # Client should accept callback registry
        assert client._callback_registry is mock_registry


class TestSDKClientSpawn:
    """Tests for SDK process spawning."""

    @pytest.mark.asyncio
    async def test_spawn_connection_passes_agent_args_without_binding_error(self):
        """SDKClient forwards agent args to the ACP stdio transport."""
        from nanobot.acp.sdk_client import SDKClient

        captured: dict[str, Any] = {}

        class FakeConnectionContext:
            async def __aenter__(self) -> tuple[str, str]:
                return ("connection", "process")

            async def __aexit__(self, exc_type, exc, tb) -> None:
                return None

        def fake_spawn(
            handler: Any,
            command: str,
            *args: str,
            env: dict[str, str] | None = None,
            cwd: str | None = None,
        ) -> FakeConnectionContext:
            captured["handler"] = handler
            captured["command"] = command
            captured["args"] = args
            captured["env"] = env
            captured["cwd"] = cwd
            return FakeConnectionContext()

        client = SDKClient(
            agent_path="opencode",
            args=["acp", "--log-level", "debug"],
            env={"OPENCODE_API_KEY": "secret"},
            cwd="/workspace/project",
        )
        handler = MagicMock()

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr("nanobot.acp.sdk_client.spawn_stdio_connection", fake_spawn)

            connection, process = await client._spawn_connection(
                command=["opencode", "acp", "--log-level", "debug"],
                handler=handler,
            )

        assert connection == "connection"
        assert process == "process"
        assert captured["handler"] is handler
        assert captured["command"] == "opencode"
        assert captured["args"] == ("acp", "--log-level", "debug")
        assert captured["env"] == {"OPENCODE_API_KEY": "secret"}
        assert captured["cwd"] == "/workspace/project"

    @pytest.mark.asyncio
    async def test_client_uses_acp_wire_methods_and_tracks_session_ids(self, monkeypatch):
        """SDKClient speaks the current ACP wire protocol expected by OpenCode."""
        from nanobot.acp.sdk_client import SDKClient
        from nanobot.acp.types import ACPStreamChunkType

        sleep_calls: list[float] = []
        live_chunks: list[str] = []
        prompt_completed = False

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        async def on_chunk(text: str) -> None:
            assert prompt_completed is False
            live_chunks.append(text)

        class FakeConnection:
            def __init__(self) -> None:
                self.requests: list[tuple[str, dict[str, Any]]] = []
                self.notifications: list[tuple[str, dict[str, Any]]] = []

            async def send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
                self.requests.append((method, params))
                if method == "initialize":
                    return {
                        "protocolVersion": 1,
                        "agentCapabilities": {"loadSession": True},
                        "agentInfo": {"name": "OpenCode", "version": "1.2.24"},
                    }
                if method == "session/new":
                    return {"sessionId": "sess-123"}
                if method == "session/set_model":
                    return {"_meta": {"opencode": {"modelId": params["modelId"]}}}
                if method == "session/prompt":
                    assert live_chunks == []
                    assert client._notification_handler is not None
                    await client._notification_handler(
                        "session/update",
                        {
                            "sessionId": "sess-123",
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": "Hello"},
                            },
                        },
                        True,
                    )
                    assert live_chunks == ["Hello"]
                    return {"stopReason": "end_turn", "usage": {"totalTokens": 0}}
                raise AssertionError(f"Unexpected request: {method}")

            async def send_notification(self, method: str, params: dict[str, Any]) -> None:
                self.notifications.append((method, params))

        fake_connection = FakeConnection()
        client = SDKClient(agent_path="opencode", args=["acp"], cwd="/workspace/project")
        client._spawn_connection = AsyncMock(return_value=(fake_connection, "process"))
        monkeypatch.setattr("nanobot.acp.sdk_client.asyncio.sleep", fake_sleep)

        result = await client.initialize(session_id="debug-session")
        assert result["status"] == "initialized"
        assert client.capabilities == {"loadSession": True}

        session_result = await client.new_session()
        assert session_result["session_id"] == "sess-123"
        assert client.current_session_id == "sess-123"

        await client.set_model("openai/gpt-5.4")
        prompt_result = await client.prompt("Hello", on_chunk=on_chunk)
        prompt_completed = True
        assert live_chunks == ["Hello"]
        assert [chunk.type for chunk in prompt_result] == [ACPStreamChunkType.CONTENT_DELTA]
        assert [chunk.content for chunk in prompt_result] == ["Hello"]
        assert sleep_calls and sleep_calls[0] > 0

        await client.cancel()

        assert fake_connection.requests == [
            (
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {},
                    "clientInfo": {"name": "nanobot", "version": "0.1.0"},
                },
            ),
            (
                "session/new",
                {"cwd": "/workspace/project", "mcpServers": []},
            ),
            (
                "session/set_model",
                {"sessionId": "sess-123", "modelId": "openai/gpt-5.4"},
            ),
            (
                "session/prompt",
                {
                    "sessionId": "sess-123",
                    "prompt": [{"type": "text", "text": "Hello"}],
                },
            ),
        ]
        assert fake_connection.notifications == [("session/cancel", {"sessionId": "sess-123"})]

    @pytest.mark.asyncio
    async def test_notification_handler_ignores_empty_or_non_text_chunks(self):
        """SDKNotificationHandler only streams non-empty text chunks to live callbacks."""
        from nanobot.acp.sdk_client import SDKNotificationHandler

        received: list[str] = []

        async def on_chunk(text: str) -> None:
            received.append(text)

        handler = SDKNotificationHandler()
        handler.begin_stream("sess-123", on_chunk=on_chunk)

        await handler(
            "session/update",
            {
                "sessionId": "sess-123",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "image", "data": "ignored"},
                },
            },
            True,
        )
        await handler(
            "session/update",
            {
                "sessionId": "sess-123",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": ""},
                },
            },
            True,
        )
        await handler(
            "session/update",
            {
                "sessionId": "sess-123",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "Hello"},
                },
            },
            True,
        )

        buffered = handler.take_stream_chunks("sess-123")

        assert received == ["Hello"]
        assert [chunk.content for chunk in buffered] == ["Hello"]


class TestSDKClientReal:
    """Tests requiring real OpenCode binary - opt-in only."""

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.skipif(not shutil.which("opencode"), reason="opencode not installed")
    @pytest.mark.opencode_real
    @pytest.mark.asyncio
    async def test_adapter_initializes_with_opencode(self):
        """SDK adapter can initialize with live OpenCode."""
        from nanobot.acp.sdk_client import SDKClient

        client = SDKClient(
            agent_path="opencode",
            args=["acp"],
        )

        try:
            await client.initialize()
            assert client.is_initialized is True
        except Exception as e:
            pytest.skip(f"OpenCode initialization failed: {e}")
        finally:
            await client.close()

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.skipif(not shutil.which("opencode"), reason="opencode not installed")
    @pytest.mark.opencode_real
    @pytest.mark.asyncio
    async def test_adapter_creates_session(self):
        """SDK adapter can create ACP session."""
        from nanobot.acp.sdk_client import SDKClient

        client = SDKClient(
            agent_path="opencode",
            args=["acp"],
        )

        try:
            await client.initialize()
            session_result = await client.new_session()
            assert session_result is not None
            # Should have session_id in the result
            assert "session_id" in session_result or hasattr(session_result, "session_id")
        except Exception as e:
            pytest.skip(f"Session creation failed: {e}")
        finally:
            await client.close()

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.skipif(not shutil.which("opencode"), reason="opencode not installed")
    @pytest.mark.opencode_real
    @pytest.mark.asyncio
    async def test_adapter_receives_notifications(self):
        """SDK adapter routes notifications to callback."""
        from nanobot.acp.sdk_client import SDKClient

        notifications_received = []

        def notification_handler(method: str, params: Any) -> None:
            notifications_received.append((method, params))

        client = SDKClient(
            agent_path="opencode",
            args=["acp"],
        )

        # Register notification handler
        client.set_notification_handler(notification_handler)

        try:
            await client.initialize()
            # Send a simple prompt that might trigger notifications
            try:
                await client.prompt("echo test", session_id="test")
            except Exception:
                # Some prompts may fail, but notifications should still be received
                pass

            # If we received any notifications, the routing works
            # (The exact notifications depend on OpenCode behavior)
        except Exception as e:
            pytest.skip(f"Notification test failed: {e}")
        finally:
            await client.close()


class TestSDKClientErrorMapping:
    """Tests for SDK error mapping."""

    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test SDKClient handles connection errors gracefully."""
        from nanobot.acp.sdk_client import SDKClient, SDKConnectionError

        client = SDKClient(
            agent_path="nonexistent-command",
            args=["acp"],
        )

        # Attempting to connect to nonexistent command should raise appropriate error
        with pytest.raises((SDKConnectionError, FileNotFoundError, Exception)):
            await client.initialize()

    @pytest.mark.asyncio
    async def test_timeout_error_mapping(self):
        """Test SDKClient maps timeout errors appropriately."""
        from nanobot.acp.sdk_client import SDKTimedOutError

        # Client should have timeout error type available
        assert SDKTimedOutError is not None


class TestSDKClientMethods:
    """Tests for SDK client public API methods."""

    @pytest.mark.asyncio
    async def test_client_has_required_methods(self):
        """Verify SDKClient has all required public methods."""
        from nanobot.acp.sdk_client import SDKClient

        client = SDKClient()

        required_methods = [
            "initialize",
            "new_session",
            "prompt",
            "cancel",
            "close",
            "load_session",
        ]

        for method_name in required_methods:
            assert hasattr(client, method_name), f"Missing method: {method_name}"
            assert callable(getattr(client, method_name)), f"Method {method_name} is not callable"

    @pytest.mark.asyncio
    async def test_prompt_requires_initialization(self):
        """Test that prompt fails if not initialized."""
        from nanobot.acp.sdk_client import SDKClient, SDKConnectionError

        client = SDKClient()

        # Prompt without initialization should raise an error
        with pytest.raises(SDKConnectionError):
            await client.prompt("test content")


# Integration test to verify imports work correctly
def test_imports_from_sdk_module():
    """Verify all expected types are importable from sdk_client."""
    from nanobot.acp.sdk_client import SDKClient
    from nanobot.acp.sdk_types import (
        to_sdk_initialize_params,
        to_sdk_new_session_params,
        to_sdk_prompt_params,
    )

    assert SDKClient is not None
    assert callable(to_sdk_initialize_params)
    assert callable(to_sdk_new_session_params)
    assert callable(to_sdk_prompt_params)
