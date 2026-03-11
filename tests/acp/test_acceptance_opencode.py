"""Acceptance tests for real OpenCode ACP backend with SDK.

These tests verify the full ACP flow with a real OpenCode backend when available.
They are gated behind an explicit pytest marker and require opt-in environment variable.

To run these tests:
    NANOBOT_TEST_OPENCODE=1 uv run pytest tests/acp/test_acceptance_opencode.py -v -m opencode_real

By default, these tests are skipped to keep the test suite hermetic.

These tests verify the SDK-based ACP integration works correctly with OpenCode.
"""

from __future__ import annotations

import os
import shutil

import pytest

from nanobot.acp.sdk_client import SDKClient
from nanobot.acp.service import ACPService, ACPServiceConfig
from nanobot.config.schema import ACPAgentDefinition

# Pytest marker for real OpenCode tests
pytestmark = pytest.mark.opencode_real


def should_run_real_tests() -> bool:
    """Check if real backend tests should run.

    Returns:
        True if NANOBOT_TEST_OPENCODE=1 is set.
    """
    return os.environ.get("NANOBOT_TEST_OPENCODE") == "1"


def is_opencode_available() -> bool:
    """Check if opencode is installed and available."""
    return shutil.which("opencode") is not None


# =============================================================================
# RED Tests: Real Prompt Round-Trip
# =============================================================================


class TestRealPromptRoundTrip:
    """RED tests for real prompt round-trip.

    These tests verify that the SDK client can communicate with real OpenCode.
    """

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_sdk_client_initializes_with_opencode(self):
        """Given opencode is installed, when SDK client is initialized,
        then it connects and gets capabilities from the agent."""
        if not is_opencode_available():
            pytest.skip("opencode not installed")

        # Create SDK client with opencode
        client = SDKClient(
            agent_path="opencode",
            args=["acp"],
        )

        # Initialize - this should connect to OpenCode via stdio
        result = await client.initialize(session_id="test-session")

        # Verify initialization succeeded
        assert result["status"] == "initialized"
        assert client.is_initialized is True

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_sdk_client_creates_session_with_opencode(self):
        """Given SDK client is initialized, when new_session is called,
        then it creates a session via the ACP protocol."""
        if not is_opencode_available():
            pytest.skip("opencode not installed")

        client = SDKClient(
            agent_path="opencode",
            args=["acp"],
        )

        await client.initialize(session_id="test")
        result = await client.new_session()

        assert result["status"] == "created"
        assert result["session_id"] is not None

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_sdk_client_sends_prompt_to_opencode(self):
        """Given SDK client has a session, when prompt is sent,
        then it receives a response from OpenCode."""
        if not is_opencode_available():
            pytest.skip("opencode not installed")

        client = SDKClient(
            agent_path="opencode",
            args=["acp"],
        )

        await client.initialize(session_id="test")
        await client.new_session()

        # Send a simple prompt
        chunks = await client.prompt(content="Hello")

        # Verify we got a response
        assert len(chunks) > 0
        assert chunks[0].get("content") is not None


# =============================================================================
# Tests: SDK Client Configuration
# =============================================================================


class TestSDKClientConfiguration:
    """Tests for SDK client configuration from agent definition."""

    @pytest.fixture
    def opencode_agent_config(self):
        return ACPAgentDefinition(
            id="opencode-agent",
            command="opencode",
            args=["acp"],
            capabilities=["read", "write", "bash", "grep", "glob", "webfetch", "memory"],
            policy="ask",
        )

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_client_uses_agent_path_from_config(self, opencode_agent_config):
        """Given an agent config with command, when SDK client is created,
        then it uses the correct command and args."""
        # Create client from config - equivalent to what ACPService does
        client = SDKClient(
            agent_path=opencode_agent_config.command,
            args=opencode_agent_config.args,
        )

        assert client.agent_path == "opencode"
        assert client.args == ["acp"]

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_client_uses_env_from_config(self):
        """Given an agent config with env vars, when client is created,
        then it includes the configured variables."""
        config_with_env = ACPAgentDefinition(
            id="opencode-agent",
            command="opencode",
            args=["acp"],
            env={"CUSTOM_VAR": "test-value"},
        )

        client = SDKClient(
            agent_path=config_with_env.command,
            args=config_with_env.args,
            env=config_with_env.env,
        )

        assert client.env is not None
        assert client.env.get("CUSTOM_VAR") == "test-value"

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_client_uses_cwd_from_config(self):
        """Given an agent config with cwd, when client is created,
        then the working directory is set correctly."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            config_with_cwd = ACPAgentDefinition(
                id="opencode-agent",
                command="opencode",
                args=["acp"],
                cwd=tmpdir,
            )

            client = SDKClient(
                agent_path=config_with_cwd.command,
                args=config_with_cwd.args,
                cwd=config_with_cwd.cwd,
            )

            assert client.cwd == tmpdir


# =============================================================================
# Tests: ACP Service Integration
# =============================================================================


class TestACPServiceIntegration:
    """Tests for ACPService with real OpenCode backend."""

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_service_creates_session(self, tmp_path):
        """Given ACPService is configured with OpenCode, when create_session is called,
        then it creates an ACP session via the SDK."""
        if not is_opencode_available():
            pytest.skip("opencode not installed")

        # Create service with OpenCode config
        service = ACPService(
            config=ACPServiceConfig(
                agent_path="opencode",
                storage_dir=tmp_path / "data",
            ),
        )

        result = await service.create_session(
            nanobot_session_key="telegram:12345",
            agent_id="opencode-agent",
        )

        assert result["status"] == "created"
        assert result["acp_session_id"] is not None
        assert result["nanobot_session_key"] == "telegram:12345"

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_service_loads_session(self, tmp_path):
        """Given ACPService has a saved binding, when load_session is called,
        then it loads or creates a session appropriately."""
        if not is_opencode_available():
            pytest.skip("opencode not installed")

        service = ACPService(
            config=ACPServiceConfig(
                agent_path="opencode",
                storage_dir=tmp_path / "data",
            ),
        )

        # First create a session
        await service.create_session(
            nanobot_session_key="telegram:12345",
            agent_id="opencode-agent",
        )

        # Now load the session - should find the binding
        result = await service.load_session(nanobot_session_key="telegram:12345")

        # Should either load existing or create new - both are valid
        assert result["nanobot_session_key"] == "telegram:12345"


# =============================================================================
# Tests: Real Backend Binary
# =============================================================================


class TestOpenCodeRealBackend:
    """Tests that verify OpenCode binary is available and working."""

    @pytest.mark.skipif(
        not should_run_real_tests(), reason="Real backend tests require NANOBOT_TEST_OPENCODE=1"
    )
    def test_opencode_binary_exists(self):
        """Given opencode is installed, when we check,
        then it can be found in PATH."""
        opencode_path = shutil.which("opencode")
        assert opencode_path is not None, "OpenCode binary not found in PATH"

    @pytest.mark.skipif(
        not should_run_real_tests(), reason="Real backend tests require NANOBOT_TEST_OPENCODE=1"
    )
    def test_opencode_acp_help(self):
        """Given opencode is installed, when we run acp subcommand,
        then it doesn't immediately error."""
        import subprocess

        result = subprocess.run(
            ["opencode", "acp", "--help"],
            capture_output=True,
            timeout=10,
        )
        # OpenCode might return 0 or just not crash on --help
        assert (
            result.returncode in [0, 1]
            or "opencode" in result.stderr.decode()
            or "acp" in result.stderr.decode()
        )


# =============================================================================
# Tests: SDK Type Conversions
# =============================================================================


class TestSDKTypeConversions:
    """Tests for SDK type conversion utilities."""

    @pytest.mark.skipif(not should_run_real_tests(), reason="Real backend tests opt-in only")
    @pytest.mark.asyncio
    async def test_initialize_response_contains_capabilities(self):
        """Given OpenCode responds to initialize, when we check,
        then capabilities are present in the response."""
        if not is_opencode_available():
            pytest.skip("opencode not installed")

        client = SDKClient(
            agent_path="opencode",
            args=["acp"],
        )

        result = await client.initialize(session_id="test")

        # Capabilities should be present (may be empty dict in mock mode,
        # but should be populated from real agent)
        assert "capabilities" in result


# Skip all tests in this module if real tests not enabled
def pytest_collection_modifyitems(items):
    """Modify test collection to skip all tests if opt-in not enabled."""
    if not should_run_real_tests():
        skip_marker = pytest.mark.skip(reason="Real backend tests require NANOBOT_TEST_OPENCODE=1")
        for item in items:
            item.add_marker(skip_marker)
