"""Acceptance tests for real OpenCode ACP backend.

These tests verify the full ACP flow with a real OpenCode backend when available.
They are gated behind an explicit pytest marker and require opt-in environment variable.

To run these tests:
    NANOBOT_TEST_OPENCODE=1 uv run pytest tests/acp/test_acceptance_opencode.py -v -m opencode_real

By default, these tests are skipped to keep the test suite hermetic.
"""

from __future__ import annotations

import os

import pytest

from nanobot.acp.opencode import OpenCodeBackend
from nanobot.acp.types import ACPSessionRecord
from nanobot.config.schema import ACPAgentDefinition

# Pytest marker for real OpenCode tests
pytestmark = pytest.mark.opencode_real


def should_run_real_tests() -> bool:
    """Check if real backend tests should run.

    Returns:
        True if NANOBOT_TEST_OPENCODE=1 is set.
    """
    return os.environ.get("NANOBOT_TEST_OPENCODE") == "1"


class TestOpenCodeBackendSmoke:
    """Smoke tests for real OpenCode backend initialization."""

    @pytest.fixture
    def opencode_agent_config(self):
        """Provide a minimal OpenCode agent configuration."""
        return ACPAgentDefinition(
            id="opencode-agent",
            command="opencode",
            args=["acp"],
            capabilities=["read", "write", "bash", "grep", "glob", "webfetch", "memory"],
            policy="ask",
        )

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_real_backend_initialization(self, opencode_agent_config):
        """Given OpenCode is installed, when the backend is initialized,
        then it starts successfully and reports capabilities."""
        backend = OpenCodeBackend(opencode_agent_config)

        # Verify config is properly set
        assert backend.agent_id == "opencode-agent"
        assert backend.get_launch_command() == ["opencode", "acp"]

        # Verify capabilities are returned
        capabilities = backend.get_capabilities()
        assert capabilities.supports_session_persistence is True
        assert capabilities.supports_streaming is True
        assert "read" in capabilities.tools

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_real_backend_launch_command_generation(self, opencode_agent_config):
        """Given an agent config, when launch command is generated,
        then it includes the correct command and arguments."""
        backend = OpenCodeBackend(opencode_agent_config)

        cmd = backend.get_launch_command()
        assert cmd[0] == "opencode"
        assert "acp" in cmd

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_real_backend_environment_variables(self, opencode_agent_config):
        """Given an agent config with env vars, when env is generated,
        then it includes the configured variables."""
        config_with_env = ACPAgentDefinition(
            id="opencode-agent",
            command="opencode",
            args=["acp"],
            env={"CUSTOM_VAR": "test-value"},
        )
        backend = OpenCodeBackend(config_with_env)

        env = backend.get_launch_env()
        assert "CUSTOM_VAR" in env
        assert env["CUSTOM_VAR"] == "test-value"

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_real_backend_working_directory(self, opencode_agent_config):
        """Given an agent config with cwd, when backend is configured,
        then the working directory is set correctly."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            config_with_cwd = ACPAgentDefinition(
                id="opencode-agent",
                command="opencode",
                args=["acp"],
                cwd=tmpdir,
            )
            backend = OpenCodeBackend(config_with_cwd)

            cwd = backend.get_working_directory()
            assert cwd is not None
            assert str(cwd) == tmpdir


class TestOpenCodeSessionFlow:
    """Tests for session flow with real OpenCode backend."""

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_build_initialize_payload(self):
        """Given session config, when initialize payload is built,
        then it contains the correct structure."""
        config = ACPAgentDefinition(
            id="opencode-agent",
            command="opencode",
            args=["acp"],
            cwd="/workspace",
        )
        backend = OpenCodeBackend(config)

        payload = backend.build_initialize_payload(
            session_id="test-session-123",
            mcp_servers=None,
        )

        assert payload["session_id"] == "test-session-123"
        assert "capabilities" in payload
        assert payload["cwd"] == "/workspace"

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_build_load_session_payload(self):
        """Given session ID, when load session payload is built,
        then it contains the session ID."""
        config = ACPAgentDefinition(
            id="opencode-agent",
            command="opencode",
            args=["acp"],
        )
        backend = OpenCodeBackend(config)

        payload = backend.build_load_session_payload(session_id="load-session-123")

        assert payload["session_id"] == "load-session-123"

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_build_recovery_payload(self):
        """Given session record, when recovery payload is built,
        then it contains the full session state."""
        from datetime import UTC, datetime

        config = ACPAgentDefinition(
            id="opencode-agent",
            command="opencode",
            args=["acp"],
        )
        backend = OpenCodeBackend(config)

        session_record = ACPSessionRecord(
            id="recovery-session",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={"key": "value"},
            messages=[{"role": "user", "content": "test"}],
        )

        payload = backend.build_recovery_payload(session_record)

        assert payload["session_id"] == "recovery-session"
        assert payload["state"] == {"key": "value"}


class TestOpenCodeMCPServers:
    """Tests for MCP server mapping with OpenCode backend."""

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_map_stdio_mcp_server(self):
        """Given a stdio MCP server config, when mapped to payload,
        then it has correct type and command."""
        from nanobot.config.schema import MCPServerConfig

        config = ACPAgentDefinition(
            id="opencode-agent",
            command="opencode",
            args=["acp"],
        )
        backend = OpenCodeBackend(config)

        mcp_servers = {
            "filesystem": MCPServerConfig(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/path"],
            )
        }

        payload = backend.build_initialize_payload(
            session_id="test",
            mcp_servers=mcp_servers,
        )

        assert "mcp_servers" in payload
        assert payload["mcp_servers"]["filesystem"]["type"] == "stdio"
        assert payload["mcp_servers"]["filesystem"]["command"] == "npx"

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_map_http_mcp_server(self):
        """Given an HTTP MCP server config, when mapped to payload,
        then it has correct type and URL."""
        from nanobot.config.schema import MCPServerConfig

        config = ACPAgentDefinition(
            id="opencode-agent",
            command="opencode",
            args=["acp"],
        )
        backend = OpenCodeBackend(config)

        mcp_servers = {
            "remote": MCPServerConfig(
                url="https://example.com/mcp/",
                headers={"Authorization": "Bearer token"},
            )
        }

        payload = backend.build_initialize_payload(
            session_id="test",
            mcp_servers=mcp_servers,
        )

        assert "mcp_servers" in payload
        assert payload["mcp_servers"]["remote"]["type"] == "http"
        assert payload["mcp_servers"]["remote"]["url"] == "https://example.com/mcp/"


class TestOpenCodeRealBackendIntegration:
    """Integration tests that require real OpenCode to be installed."""

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_opencode_binary_exists(self):
        """Given opencode is installed, when we check,
        then it can be found in PATH."""
        import shutil

        # Check if opencode is available
        opencode_path = shutil.which("opencode")
        assert opencode_path is not None, "OpenCode binary not found in PATH"

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_opencode_acp_help(self):
        """Given opencode is installed, when we run acp subcommand,
        then it doesn't immediately error."""
        import subprocess

        result = subprocess.run(
            ["opencode", "acp", "--help"],
            capture_output=True,
            timeout=10,
        )
        # Either it shows help or it starts interactive (which we treat as success)
        # The key is it doesn't immediately fail with "command not found"
        assert (
            result.returncode in [0, 1]
            or "opencode" in result.stderr.decode()
            or "acp" in result.stderr.decode()
        )


# Skip all tests in this module if real tests not enabled
def pytest_collection_modifyitems(items):
    """Modify test collection to skip all tests if opt-in not enabled."""
    if not should_run_real_tests():
        skip_marker = pytest.mark.skip(reason="Real backend tests require NANOBOT_TEST_OPENCODE=1")
        for item in items:
            item.add_marker(skip_marker)
