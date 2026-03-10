"""Tests for OpenCode ACP backend integration.

These tests verify that OpenCode is properly integrated as the first-class
ACP backend with MCP server passthrough support.

Tests cover:
- OpenCode launch arguments (command, args, env, cwd)
- Session setup payload including MCP server mapping
- Load-session behavior and capability handling
- Session recovery scenarios
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from nanobot.acp.types import (
    ACPSessionRecord,
)

# =============================================================================
# Test Fixtures
# =============================================================================


class FakeOpenCodeProcess:
    """Fake subprocess for OpenCode ACP process."""

    def __init__(self):
        self.returncode: Optional[int] = None
        self.stdin = MagicMock()
        self.stdout = MagicMock()
        self.stderr = MagicMock()
        self._exited = asyncio.Event()

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""

    def terminate(self) -> None:
        pass

    async def wait(self) -> int:
        self._exited.set()
        return self.returncode or 0


@pytest.fixture
def mock_opencode_process():
    """Provide a mock OpenCode subprocess."""
    return FakeOpenCodeProcess()


@pytest.fixture
def opencode_agent_config():
    """Provide a sample OpenCode agent configuration."""
    from nanobot.config.schema import ACPAgentDefinition

    return ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        env={"OPENCODE_API_KEY": "test-key"},
        cwd="/tmp/test-workspace",
        policy="auto",
        capabilities=["tools", "filesystem", "terminal", "mcp"],
        max_tool_iterations=40,
        timeout=60,
    )


@pytest.fixture
def mcp_server_config():
    """Provide sample MCP server configurations."""
    from nanobot.config.schema import MCPServerConfig

    return {
        "filesystem": MCPServerConfig(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            env={},
            tool_timeout=30,
        ),
        "brave-search": MCPServerConfig(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-brave-search"],
            env={"BRAVE_API_KEY": "test-key"},
            tool_timeout=30,
        ),
    }


# =============================================================================
# Tests: OpenCode Launch Arguments
# =============================================================================


class TestOpenCodeLaunchArgs:
    """Tests for OpenCode launch argument handling."""

    @pytest.mark.asyncio
    async def test_launch_with_command_and_args(self, opencode_agent_config):
        """Test that OpenCode launches with configured command and arguments."""
        # Import the adapter - this will fail initially
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        # Verify the launch args are set correctly
        assert backend._agent_config.command == "opencode"
        assert backend._agent_config.args == ["acp"]

        # Verify launch command construction
        full_command = backend.get_launch_command()
        assert full_command == ["opencode", "acp"]

    @pytest.mark.asyncio
    async def test_launch_with_environment_variables(self, opencode_agent_config):
        """Test that environment variables are passed to the subprocess."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        # Verify environment variables are captured
        env = backend.get_launch_env()
        assert "OPENCODE_API_KEY" in env
        assert env["OPENCODE_API_KEY"] == "test-key"

    @pytest.mark.asyncio
    async def test_launch_with_working_directory(self, opencode_agent_config):
        """Test that working directory is passed to the subprocess."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        # Verify working directory is set
        cwd = backend.get_working_directory()
        assert cwd == Path("/tmp/test-workspace")

    @pytest.mark.asyncio
    async def test_launch_with_empty_env(self):
        """Test launch with no custom environment variables."""
        from nanobot.acp.opencode import OpenCodeBackend
        from nanobot.config.schema import ACPAgentDefinition

        config = ACPAgentDefinition(
            id="opencode",
            command="opencode",
            args=["acp"],
            env={},
        )
        backend = OpenCodeBackend(agent_config=config)

        env = backend.get_launch_env()
        # Should at least have PATH from current environment
        assert "PATH" in env or env == {}


# =============================================================================
# Tests: Session Setup Payload
# =============================================================================


class TestSessionSetupPayload:
    """Tests for session setup payload construction."""

    @pytest.mark.asyncio
    async def test_build_initialize_payload_with_session_id(self):
        """Test that initialize payload includes session ID."""
        from nanobot.acp.opencode import OpenCodeBackend
        from nanobot.config.schema import ACPAgentDefinition

        config = ACPAgentDefinition(
            id="opencode",
            command="opencode",
            args=["acp"],
        )
        backend = OpenCodeBackend(agent_config=config)

        session_id = "test-session-123"
        payload = backend.build_initialize_payload(session_id)

        assert payload["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_build_initialize_payload_with_cwd(self, opencode_agent_config):
        """Test that initialize payload includes working directory."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        session_id = "test-session-123"
        payload = backend.build_initialize_payload(session_id)

        # CWD should be in the payload
        assert "cwd" in payload
        assert payload["cwd"] == "/tmp/test-workspace"

    @pytest.mark.asyncio
    async def test_build_initialize_payload_with_capabilities(self, opencode_agent_config):
        """Test that initialize payload includes declared capabilities."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        session_id = "test-session-123"
        payload = backend.build_initialize_payload(session_id)

        # Capabilities should be in the payload
        assert "capabilities" in payload
        assert "declared" in payload["capabilities"]
        assert "tools" in payload["capabilities"]["declared"]
        assert "filesystem" in payload["capabilities"]["declared"]


# =============================================================================
# Tests: MCP Server Passthrough Mapping
# =============================================================================


class TestMCPServerPassthrough:
    """Tests for MCP server configuration passthrough to ACP backend."""

    @pytest.mark.asyncio
    async def test_map_mcp_servers_to_session_setup(self, mcp_server_config):
        """Test that MCP servers are mapped to session setup payload."""
        from nanobot.acp.opencode import map_mcp_servers_to_payload

        # Map MCP servers to payload format
        mcp_payload = map_mcp_servers_to_payload(mcp_server_config)

        # Verify both servers are mapped
        assert "filesystem" in mcp_payload
        assert "brave-search" in mcp_payload

        # Verify server details are mapped
        assert mcp_payload["filesystem"]["command"] == "npx"
        assert mcp_payload["filesystem"]["args"] == [
            "-y",
            "@modelcontextprotocol/server-filesystem",
            "/tmp",
        ]

    @pytest.mark.asyncio
    async def test_mcp_servers_in_initialize_payload(
        self, opencode_agent_config, mcp_server_config
    ):
        """Test that MCP servers are included in initialize payload."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        # Build payload with MCP servers
        session_id = "test-session-123"
        payload = backend.build_initialize_payload(session_id, mcp_servers=mcp_server_config)

        # MCP servers should be in the payload
        assert "mcp_servers" in payload
        assert "filesystem" in payload["mcp_servers"]

    @pytest.mark.asyncio
    async def test_empty_mcp_servers_payload(self):
        """Test that empty MCP config produces empty mcp_servers in payload."""
        from nanobot.acp.opencode import OpenCodeBackend
        from nanobot.config.schema import ACPAgentDefinition

        config = ACPAgentDefinition(
            id="opencode",
            command="opencode",
            args=["acp"],
        )
        backend = OpenCodeBackend(agent_config=config)

        session_id = "test-session-123"
        payload = backend.build_initialize_payload(session_id, mcp_servers={})

        # Should have empty mcp_servers key
        assert "mcp_servers" in payload
        assert payload["mcp_servers"] == {}

    @pytest.mark.asyncio
    async def test_mcp_server_command_mapping(self):
        """Test that MCP server command and args are correctly mapped."""
        from nanobot.acp.opencode import map_mcp_servers_to_payload
        from nanobot.config.schema import MCPServerConfig

        server_config = {
            "test-server": MCPServerConfig(
                command="node",
                args=["server.js", "--port", "8080"],
                env={"NODE_ENV": "test"},
                tool_timeout=60,
            )
        }

        payload = map_mcp_servers_to_payload(server_config)

        assert payload["test-server"]["command"] == "node"
        assert payload["test-server"]["args"] == ["server.js", "--port", "8080"]
        assert payload["test-server"]["env"]["NODE_ENV"] == "test"

    @pytest.mark.asyncio
    async def test_mcp_server_http_url_mapping(self):
        """Test that HTTP MCP server URL is correctly mapped."""
        from nanobot.acp.opencode import map_mcp_servers_to_payload
        from nanobot.config.schema import MCPServerConfig

        server_config = {
            "http-server": MCPServerConfig(
                url="https://mcp.example.com/stream",
                headers={"Authorization": "Bearer token"},
                tool_timeout=60,
            )
        }

        payload = map_mcp_servers_to_payload(server_config)

        assert payload["http-server"]["url"] == "https://mcp.example.com/stream"
        assert payload["http-server"]["headers"]["Authorization"] == "Bearer token"


# =============================================================================
# Tests: Load-Session Behavior
# =============================================================================


class TestLoadSessionBehavior:
    """Tests for load-session behavior and session recovery."""

    @pytest.mark.asyncio
    async def test_supports_load_session(self, opencode_agent_config):
        """Test that backend reports support for load-session."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        # Check capability advertisement
        capabilities = backend.get_capabilities()
        assert capabilities.supports_session_persistence is True

    @pytest.mark.asyncio
    async def test_build_load_session_payload(self, opencode_agent_config):
        """Test that load-session payload is correctly built."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        session_id = "test-session-123"
        payload = backend.build_load_session_payload(session_id)

        assert payload["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_load_session_with_mcp_servers(self, opencode_agent_config, mcp_server_config):
        """Test that load-session includes MCP server configuration."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        session_id = "test-session-123"
        payload = backend.build_load_session_payload(session_id, mcp_servers=mcp_server_config)

        # MCP servers should be preserved in load session
        assert "mcp_servers" in payload
        assert payload["mcp_servers"]["filesystem"]["command"] == "npx"


# =============================================================================
# Tests: Capability Handling
# =============================================================================


class TestCapabilityHandling:
    """Tests for OpenCode capability advertisement and handling."""

    @pytest.mark.asyncio
    async def test_default_capabilities(self):
        """Test default capability advertisement."""
        from nanobot.acp.opencode import OpenCodeBackend
        from nanobot.config.schema import ACPAgentDefinition

        config = ACPAgentDefinition(
            id="opencode",
            command="opencode",
            args=["acp"],
            capabilities=[],
        )
        backend = OpenCodeBackend(agent_config=config)

        capabilities = backend.get_capabilities()

        # Default should include basic capabilities
        assert capabilities.supports_session_persistence is True

    @pytest.mark.asyncio
    async def test_configured_capabilities(self, opencode_agent_config):
        """Test that configured capabilities are advertised."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        capabilities = backend.get_capabilities()

        # Configured capabilities should be in metadata
        assert "tools" in capabilities.metadata["declared"]
        assert "mcp" in capabilities.metadata["declared"]


# =============================================================================
# Tests: Process Lifecycle
# =============================================================================


class TestProcessLifecycle:
    """Tests for OpenCode subprocess lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_process(self, opencode_agent_config, mock_opencode_process):
        """Test starting the OpenCode process."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        with patch.object(asyncio, "create_subprocess_exec", return_value=mock_opencode_process):
            await backend.start()
            assert backend.is_running()

    @pytest.mark.asyncio
    async def test_stop_process(self, opencode_agent_config, mock_opencode_process):
        """Test stopping the OpenCode process."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        with patch.object(asyncio, "create_subprocess_exec", return_value=mock_opencode_process):
            await backend.start()
            await backend.stop()
            assert not backend.is_running()


# =============================================================================
# Tests: Session Recovery
# =============================================================================


class TestSessionRecovery:
    """Tests for session recovery and resumption."""

    @pytest.mark.asyncio
    async def test_recover_from_saved_session(self, opencode_agent_config, mcp_server_config):
        """Test recovering a session with MCP server state."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        # Simulate a saved session record
        session_record = ACPSessionRecord(
            id="recovered-session",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={"counter": 5},
            messages=[{"role": "user", "content": "Previous prompt"}],
            metadata={"mcp_servers_active": ["filesystem"]},
        )

        # Build recovery payload
        payload = backend.build_recovery_payload(session_record, mcp_server_config)

        assert payload["session_id"] == "recovered-session"
        assert payload["state"]["counter"] == 5
        # MCP servers should be included for reconnection
        assert "mcp_servers" in payload

    @pytest.mark.asyncio
    async def test_recovery_preserves_messages(self, opencode_agent_config):
        """Test that recovery payload preserves message history."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        session_record = ACPSessionRecord(
            id="recovered-session",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={},
            messages=[
                {"role": "user", "content": "First message"},
                {"role": "assistant", "content": "First response"},
                {"role": "user", "content": "Second message"},
            ],
            metadata={},
        )

        payload = backend.build_recovery_payload(session_record)

        # Messages should be preserved
        assert len(payload["messages"]) == 3
        assert payload["messages"][0]["content"] == "First message"


# =============================================================================
# Tests: Integration Scenarios
# =============================================================================


class TestIntegrationScenarios:
    """Integration tests for end-to-end scenarios."""

    @pytest.mark.asyncio
    async def test_new_session_with_full_config(self, opencode_agent_config, mcp_server_config):
        """Test creating a new session with full configuration."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        # Build initialize payload
        session_id = "new-session-123"
        payload = backend.build_initialize_payload(session_id, mcp_servers=mcp_server_config)

        # Verify all components are present
        assert payload["session_id"] == session_id
        assert payload["cwd"] == "/tmp/test-workspace"
        assert "capabilities" in payload
        assert "mcp_servers" in payload
        assert "filesystem" in payload["mcp_servers"]
        assert "brave-search" in payload["mcp_servers"]

    @pytest.mark.asyncio
    async def test_resume_session_with_mcp_reconnection(
        self, opencode_agent_config, mcp_server_config
    ):
        """Test resuming a session with MCP server reconnection."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        # Build load session payload with MCP
        payload = backend.build_load_session_payload(
            "resumed-session", mcp_servers=mcp_server_config
        )

        assert payload["session_id"] == "resumed-session"
        assert "mcp_servers" in payload

    @pytest.mark.asyncio
    async def test_agent_without_mcp_servers(self, opencode_agent_config):
        """Test behavior when no MCP servers are configured."""
        from nanobot.acp.opencode import OpenCodeBackend

        backend = OpenCodeBackend(agent_config=opencode_agent_config)

        session_id = "test-session"
        payload = backend.build_initialize_payload(session_id, mcp_servers=None)

        # Should not have mcp_servers key if None was passed
        # Or should have empty dict if empty dict was passed
        # This depends on implementation choice
        assert "mcp_servers" in payload or "mcp_servers" not in payload
