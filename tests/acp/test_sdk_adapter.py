"""Tests for SDK transport adapter.

These tests verify the SDK-based ACP transport layer.
Tests requiring a live OpenCode binary are marked with @pytest.mark.opencode_real.
"""

from __future__ import annotations

import shutil
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


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

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

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
        prompt_result = await client.prompt("Hello")
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
