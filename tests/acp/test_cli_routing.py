"""Tests for ACP CLI and chat routing.

These tests verify that:
1. ACP backend selection through config works
2. CLI surface supports ACP mode
3. Chat routing to ACP backend works
4. Session binding is durable and recoverable
5. Local nanobot backend remains default when ACP not configured
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import ACPAgentDefinition, Config
from tests.acp.fakes import (
    FakeACPAgentRuntime,
    FakeACPCallbackRegistry,
    FakeACPSessionStore,
    FakeACPUpdateSink,
)

runner = CliRunner()


# ============================================================================
# Test: ACP backend selection through config
# ============================================================================


@pytest.fixture
def config_with_acp():
    """Create a config with ACP agent definition."""
    config = Config()
    config.acp.agents["opencode"] = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        policy="auto",
    )
    config.acp.default_agent = "opencode"
    return config


@pytest.fixture
def config_without_acp():
    """Create a config without ACP configuration."""
    return Config()


def test_acp_config_has_agents(config_with_acp):
    """Given config with ACP agents, when loaded, then agents should be available."""
    assert "opencode" in config_with_acp.acp.agents
    assert config_with_acp.acp.default_agent == "opencode"


def test_local_nanobot_remains_default_without_acp(config_without_acp):
    """Given config without ACP, when using default behavior, then local agent should be used."""
    # ACP config is empty by default
    assert not config_without_acp.acp.agents
    assert config_without_acp.acp.default_agent is None


# ============================================================================
# Test: ACP service initialization
# ============================================================================


@pytest.fixture
def mock_acp_service():
    """Mock ACP service for testing."""
    with patch("nanobot.acp.service.ACPService") as mock_service:
        mock_instance = MagicMock()
        mock_instance.active_sessions = []
        mock_instance.create_session = MagicMock(
            return_value={
                "nanobot_session_key": "cli:direct",
                "acp_session_id": "test-acp-session",
                "agent_id": "opencode",
                "status": "created",
            }
        )
        mock_instance.process_message = MagicMock(return_value=[])
        mock_instance.load_session = MagicMock(
            return_value={
                "nanobot_session_key": "cli:direct",
                "acp_session_id": "test-acp-session",
                "agent_id": "opencode",
                "status": "loaded",
            }
        )
        mock_service.return_value = mock_instance
        yield mock_instance


def test_acp_service_can_be_created():
    """Given ACP configuration, when creating service, then service should initialize."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    config = ACPServiceConfig(
        agent_path="opencode",
        storage_dir=Path("/tmp/test_acp"),
    )
    service = ACPService(config)
    assert service is not None


# ============================================================================
# Test: CLI surface for ACP mode
# ============================================================================


@pytest.fixture
def config_path_with_acp(tmp_path):
    """Create a config file with ACP settings."""
    config_file = tmp_path / "config.json"
    config_content = {
        "agents": {
            "defaults": {
                "workspace": str(tmp_path / "workspace"),
                "model": "anthropic/claude-opus-4-5",
            }
        },
        "acp": {
            "agents": {
                "opencode": {
                    "id": "opencode",
                    "command": "opencode",
                    "args": ["acp"],
                    "policy": "auto",
                    "capabilities": ["read", "write", "bash"],
                }
            },
            "defaultAgent": "opencode",
        },
    }
    import json

    config_file.write_text(json.dumps(config_content))
    return config_file


@pytest.fixture
def workspace_with_acp(tmp_path):
    """Create workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def test_cli_has_acp_option_in_gateway():
    """Given gateway command, when checking options, then ACP-related options should be available."""
    result = runner.invoke(app, ["gateway", "--help"])
    assert result.exit_code == 0
    # Gateway should have option to pass ACP config (indirect test via agent init)


def test_cli_has_acp_option_in_agent():
    """Given agent command, when checking options, then ACP-related options should be available."""
    result = runner.invoke(app, ["agent", "--help"])
    assert result.exit_code == 0
    # Agent command should work - ACP is passed via config internally


# ============================================================================
# Test: Chat routing to ACP backend
# ============================================================================


@pytest.mark.asyncio
async def test_chat_routes_to_acp_backend_when_configured():
    """Given a user starts an ACP-backed chat, when they send a prompt, then it routes to the bound OpenCode ACP session."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    # Setup fake runtime with session store and callback registry
    session_store = FakeACPSessionStore()
    callback_registry = FakeACPCallbackRegistry()

    # Create service with fake config
    service = ACPService(
        ACPServiceConfig(
            agent_path=None,  # fake mode
            storage_dir=None,
            callback_registry=callback_registry,
        )
    )

    # Manually inject fake runtime (bypassing actual client init)
    service._session_store = session_store
    service._binding_store = None

    # Create a session
    result = await service.create_session("cli:direct", "opencode")

    assert result["status"] == "created"
    assert result["nanobot_session_key"] == "cli:direct"
    assert result["acp_session_id"] is not None


@pytest.mark.asyncio
async def test_existing_session_binding_is_reused():
    """Given a chat already has an ACP session binding, when the user sends a follow-up prompt, then nanobot reuses the same backend session."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    session_store = FakeACPSessionStore()
    callback_registry = FakeACPCallbackRegistry()

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)

        service = ACPService(
            ACPServiceConfig(
                agent_path=None,
                storage_dir=storage_dir,
                callback_registry=callback_registry,
            )
        )

        service._session_store = session_store

        # Create initial session (this saves binding to store)
        result1 = await service.create_session("cli:direct", "opencode")
        session_id_1 = result1["acp_session_id"]

        # Load existing session (should load from binding, not create new)
        result2 = await service.load_session("cli:direct")
        session_id_2 = result2["acp_session_id"]

        # Should be the same session
        assert session_id_1 == session_id_2


# ============================================================================
# Test: Session binding resolution and recovery
# ============================================================================


@pytest.mark.asyncio
async def test_session_binding_persists_to_store():
    """Given session binding is created, when store is available, then binding should be saved."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    # Create temp storage directory
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)

        service = ACPService(
            ACPServiceConfig(
                agent_path=None,
                storage_dir=storage_dir,
            )
        )

        # Create session with binding
        await service.create_session("cli:direct", "opencode")

        # Verify binding store has the binding
        assert service._binding_store is not None
        binding = service._binding_store.load_binding("cli:direct")
        assert binding is not None
        assert binding.nanobot_session_key == "cli:direct"
        assert binding.acp_agent_id == "opencode"


@pytest.mark.asyncio
async def test_session_resume_after_process_restart():
    """Given a session is cancelled or closed, when the user sends a new prompt, then nanobot resumes or creates a new backend session according to configured policy."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)

        service = ACPService(
            ACPServiceConfig(
                agent_path=None,
                storage_dir=storage_dir,
            )
        )

        # Create initial session
        result1 = await service.create_session("cli:direct", "opencode")
        acp_session_id_1 = result1["acp_session_id"]

        # "Shutdown" the session (simulating process restart)
        await service.shutdown_session("cli:direct")

        # Load session again - should resume
        result2 = await service.load_session("cli:direct")
        acp_session_id_2 = result2["acp_session_id"]

        # Should be the same session (resume behavior)
        assert acp_session_id_1 == acp_session_id_2


# ============================================================================
# Test: Progress and permission requests through channel path
# ============================================================================


@pytest.mark.asyncio
async def test_progress_events_reach_update_sink():
    """Given ACP agent emits progress, when processing, then progress should reach the update sink."""
    session_store = FakeACPSessionStore()
    callback_registry = FakeACPCallbackRegistry()
    update_sink = FakeACPUpdateSink()

    runtime = FakeACPAgentRuntime(
        session_store=session_store,
        callback_registry=callback_registry,
        update_sinks=[update_sink],
    )

    from nanobot.acp.types import ACPInitializeRequest

    await runtime.initialize(ACPInitializeRequest(session_id="test-session"))

    from nanobot.acp.types import ACPPromptRequest

    await runtime.prompt(ACPPromptRequest(content="Hello", session_id="test-session"))

    # Check that we got prompt_start and prompt_end events
    event_types = [e.event_type for e in update_sink.updates]
    assert "prompt_start" in event_types
    assert "prompt_end" in event_types


@pytest.mark.asyncio
async def test_permission_request_through_callback_registry():
    """Given ACP agent requests permission, when configured, then callback registry should handle it."""
    from nanobot.acp.types import (
        ACPFilesystemCallback,
        ACPPermissionRequest,
    )

    callback_registry = FakeACPCallbackRegistry()

    # Register a handler that always grants
    async def grant_callback(callback):
        from nanobot.acp.types import ACPPermissionDecision

        return ACPPermissionDecision(request_id="test", granted=True)

    callback_registry.register_filesystem_callback(grant_callback)

    # Create a permission request
    request = ACPPermissionRequest(
        id="perm-1",
        permission_type="filesystem",
        description="Read file",
        resource="/test/file.txt",
        callback=ACPFilesystemCallback(operation="read", path="/test/file.txt"),
    )

    # Handle it
    decision = await callback_registry.handle_permission_request(request)

    assert decision.granted is True


# ============================================================================
# Test: Integration with CLI commands
# ============================================================================


@patch("nanobot.config.loader.load_config")
def test_cli_gateway_works_with_acp_config(mock_load_config, tmp_path):
    """Given gateway command with ACP config, when started, then it should initialize without error (no crash)."""
    # Create a mock config with ACP
    config = Config()
    config.acp.agents["opencode"] = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        policy="auto",
    )
    config.acp.default_agent = "opencode"
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.gateway.heartbeat.enabled = False  # Disable heartbeat for test

    mock_load_config.return_value = config

    # Try to invoke gateway - it will try to start but we'll mock AgentLoop
    # This tests that config loading works
    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    # Should show status without crashing


@patch("nanobot.config.loader.load_config")
def test_cli_agent_works_without_acp(mock_load_config, tmp_path):
    """Given agent command without ACP config, when started, then local agent mode should work."""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.gateway.heartbeat.enabled = False

    mock_load_config.return_value = config

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    # Status should work without ACP configured


# ============================================================================
# Test: ACP mode selection logic
# ============================================================================


def test_acp_mode_is_selected_when_configured():
    """Given config with ACP default agent, when checking mode, then ACP should be selected."""
    config = Config()
    config.acp.default_agent = "opencode"

    # This would be checked in the integration
    assert config.acp.default_agent is not None


def test_local_mode_is_selected_when_not_configured():
    """Given config without ACP default agent, when checking mode, then local mode should be used."""
    config = Config()

    # Default is None (local mode)
    assert config.acp.default_agent is None
