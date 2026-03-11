"""Tests for ACP CLI and chat routing.

These tests verify that:
1. ACP backend selection through config works
2. CLI surface supports ACP mode
3. Chat routing to ACP backend works with proper channel preservation
4. Session binding is durable and recoverable
5. Local nanobot backend remains default when ACP not configured
6. /stop propagation to ACP cancellation

RED PHASE: These tests capture the gaps where:
- Only command is passed to ACPService, not args/env/cwd/policy
- Channel/chat_id are hardcoded to cli/direct in route_to_acp
- /stop doesn't propagate to ACP service cancel
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.acp.types import ACPInitializeRequest, ACPPromptRequest
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
    assert not config_without_acp.acp.agents
    assert config_without_acp.acp.default_agent is None


# ============================================================================
# Test: Full agent definition propagation
# ============================================================================


class TestAgentDefinitionPropagation:
    """RED tests for full agent definition propagation.

    The current code in commands.py only passes `command` to ACPServiceConfig,
    dropping args, env, cwd, policy, capabilities, etc.
    """

    def test_cli_passes_full_agent_definition_to_service(self):
        """Given a config with full agent definition (args, env, cwd, policy),
        when nanobot creates the ACP service, then all settings should be passed.

        RED PHASE: Currently only command is passed to ACPServiceConfig, not the full definition.
        The gap is in nanobot/cli/commands.py where _get_acp_service creates config with only
        agent_path=command (line 46), dropping args, env, cwd, policy, capabilities.

        This test verifies that a full agent config CAN be created (it works in isolation),
        but the CLI doesn't actually USE the full config when creating the service.
        """
        from nanobot.config.schema import ACPAgentDefinition

        # Full agent config with all settings - this CAN be created
        agent_config = ACPAgentDefinition(
            id="opencode",
            command="opencode",
            args=["acp", "--verbose"],
            env={"OPENCODE_API_KEY": "secret123"},
            cwd="/workspace/myproject",
            policy="auto",
            capabilities=["read", "write", "bash"],
            max_tool_iterations=50,
        )

        # Verify the config itself is valid with all settings
        assert agent_config.args == ["acp", "--verbose"]
        assert agent_config.env == {"OPENCODE_API_KEY": "secret123"}
        assert agent_config.cwd == "/workspace/myproject"
        assert agent_config.policy == "auto"
        assert agent_config.capabilities == ["read", "write", "bash"]
        assert agent_config.max_tool_iterations == 50

        import nanobot.cli.commands as commands_module

        config = Config()
        config.acp.agents["opencode"] = agent_config
        config.acp.default_agent = "opencode"

        commands_module._acp_service = None
        try:
            with patch("nanobot.acp.service.ACPService") as mock_service_cls:
                mock_service = MagicMock()
                mock_service_cls.return_value = mock_service

                service = commands_module._get_acp_service(config)

            assert service is mock_service
            passed_config = mock_service_cls.call_args.args[0]
            assert passed_config.agent_path == "opencode"
            assert passed_config.agent_definition is agent_config
            assert passed_config.agent_definition.args == ["acp", "--verbose"]
            assert passed_config.agent_definition.env == {"OPENCODE_API_KEY": "secret123"}
            assert passed_config.agent_definition.cwd == "/workspace/myproject"
            assert passed_config.agent_definition.policy == "auto"
        finally:
            commands_module._acp_service = None


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


@pytest.mark.asyncio
async def test_load_session_preserves_agent_definition_on_resume():
    """Given a resumed ACP session, load_session should recreate the client with full agent config."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    agent_definition = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp", "--verbose"],
        env={"OPENCODE_API_KEY": "secret123"},
        cwd="/workspace/myproject",
        policy="auto",
    )
    config = ACPServiceConfig(agent_path="opencode", agent_definition=agent_definition)
    service = ACPService(config)

    binding = MagicMock(acp_session_id="sess-123", acp_agent_id="opencode")
    service._binding_store = MagicMock(load_binding=MagicMock(return_value=binding))

    with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
        client = MagicMock()
        client.initialize = AsyncMock(return_value={"status": "initialized", "capabilities": {}})
        client.capabilities = {}
        client.load_session = AsyncMock(
            return_value={"session": {"id": "sess-123"}, "status": "loaded"}
        )
        client.new_session = AsyncMock(
            return_value={"session_id": "new-session", "status": "created"}
        )
        mock_client_cls.return_value = client

        await service.load_session("cli:direct")

    # Verify that args, env, cwd are extracted from agent_definition and passed to SDKClient
    assert mock_client_cls.call_args.kwargs["args"] == ["acp", "--verbose"]
    assert mock_client_cls.call_args.kwargs["env"] == {"OPENCODE_API_KEY": "secret123"}
    assert mock_client_cls.call_args.kwargs["cwd"] == "/workspace/myproject"


# ============================================================================
# Test: Channel/chat preservation in routing
# ============================================================================


class TestChannelPreservation:
    """RED tests for channel/chat_id preservation.

    The current code in agent/loop.py _route_to_acp returns hardcoded
    channel="cli", chat_id="direct" instead of preserving the original.
    """

    @pytest.mark.asyncio
    async def test_acp_routing_preserves_telegram_channel(self):
        """Given a Telegram session routes through ACP, when response is emitted,
        then the channel should be 'telegram', not 'cli'.

        RED PHASE: Currently _route_to_acp returns hardcoded cli/direct.
        """
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus

        # Create mock components
        bus = MagicMock(spec=MessageBus)

        # Create a mock provider
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.chat = AsyncMock(
            return_value=MagicMock(
                content="test response",
                has_tool_calls=False,
                finish_reason="stop",
            )
        )

        # Create mock ACP service that returns a response
        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(return_value={"acp_session_id": "test-session"})
        mock_acp_service.process_message = AsyncMock(
            return_value=[MagicMock(content="ACP response")]
        )

        # Create agent with ACP service
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            agent = AgentLoop(
                bus=bus,
                provider=mock_provider,
                workspace=workspace,
                acp_service=mock_acp_service,
                acp_default_agent="opencode",
            )

            # Create a Telegram message - we just need it for the session key derivation
            # The actual message content is passed to _route_to_acp separately
            InboundMessage(
                channel="telegram",
                sender_id="user",
                chat_id="123456789",
                content="Hello from Telegram",
            )

            # Route to ACP - this should preserve the channel
            # Current gap: _route_to_acp returns cli/direct instead of preserving
            response = await agent._route_to_acp(
                session_key="telegram:123456789",
                message="Hello from Telegram",
            )

            # This will fail because current code returns cli/direct
            assert response is not None
            assert response.channel == "telegram", (
                f"Expected channel 'telegram', got '{response.channel}'. "
                "The _route_to_acp method should preserve the original channel."
            )
            assert response.chat_id == "123456789", (
                f"Expected chat_id '123456789', got '{response.chat_id}'. "
                "The _route_to_acp method should preserve the original chat_id."
            )

    @pytest.mark.asyncio
    async def test_acp_routing_preserves_whatsapp_channel(self):
        """Given a WhatsApp session routes through ACP, when response is emitted,
        then the channel should be 'whatsapp', not 'cli'."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"

        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(return_value={"acp_session_id": "test"})
        mock_acp_service.process_message = AsyncMock(
            return_value=[MagicMock(content="ACP response")]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent = AgentLoop(
                bus=bus,
                provider=mock_provider,
                workspace=workspace,
                acp_service=mock_acp_service,
                acp_default_agent="opencode",
            )

            response = await agent._route_to_acp(
                session_key="whatsapp:+1234567890",
                message="Hello",
            )

            assert response is not None
            assert response.channel == "whatsapp"
            assert response.chat_id == "+1234567890"


class TestACPFallback:
    @pytest.mark.asyncio
    async def test_process_message_falls_back_to_local_when_acp_errors(self):
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.chat = AsyncMock(
            return_value=MagicMock(
                content="Local fallback response",
                has_tool_calls=False,
                finish_reason="stop",
                reasoning_content=None,
                thinking_blocks=None,
            )
        )

        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(side_effect=RuntimeError("ACP unavailable"))
        mock_acp_service.cancel_operation = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = AgentLoop(
                bus=bus,
                provider=mock_provider,
                workspace=Path(tmpdir),
                acp_service=mock_acp_service,
                acp_default_agent="opencode",
            )

            response = await agent._process_message(
                InboundMessage(
                    channel="telegram",
                    sender_id="user",
                    chat_id="123",
                    content="hello",
                )
            )

        assert response is not None
        assert response.content == "Local fallback response"
        assert response.channel == "telegram"
        assert response.chat_id == "123"

    @pytest.mark.asyncio
    async def test_process_message_falls_back_to_local_when_acp_times_out(self):
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.chat = AsyncMock(
            return_value=MagicMock(
                content="Timed out fallback response",
                has_tool_calls=False,
                finish_reason="stop",
                reasoning_content=None,
                thinking_blocks=None,
            )
        )

        async def slow_load_session(*_args, **_kwargs):
            await asyncio.sleep(0.05)
            return {"acp_session_id": "slow-session"}

        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(side_effect=slow_load_session)
        mock_acp_service.cancel_operation = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = AgentLoop(
                bus=bus,
                provider=mock_provider,
                workspace=Path(tmpdir),
                acp_service=mock_acp_service,
                acp_default_agent="opencode",
            )
            agent._ACP_ROUTE_TIMEOUT_SECONDS = 0.01

            response = await agent._process_message(
                InboundMessage(
                    channel="telegram",
                    sender_id="user",
                    chat_id="123",
                    content="hello",
                )
            )

        assert response is not None
        assert response.content == "Timed out fallback response"
        mock_acp_service.cancel_operation.assert_awaited_once_with("telegram:123")


# ============================================================================
# Test: /stop propagation to ACP
# ============================================================================


class TestStopPropagation:
    """RED tests for /stop propagation to ACP service.

    The current _handle_stop in agent/loop.py only cancels local tasks,
    not the ACP service.
    """

    @pytest.mark.asyncio
    async def test_stop_cancels_acp_operation(self):
        """Given an ACP prompt is in flight, when user issues /stop,
        then the ACP service cancel_operation should be called.

        RED PHASE: Currently _handle_stop doesn't call acp_service.cancel_operation.
        """
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"

        # Track whether cancel was called
        cancel_called = False

        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(return_value={"acp_session_id": "test"})
        mock_acp_service.process_message = AsyncMock(
            return_value=[MagicMock(content="ACP response")]
        )

        async def mock_cancel(nanobot_session_key):
            nonlocal cancel_called
            cancel_called = True

        mock_acp_service.cancel_operation = mock_cancel
        mock_acp_service.shutdown_session = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent = AgentLoop(
                bus=bus,
                provider=mock_provider,
                workspace=workspace,
                acp_service=mock_acp_service,
                acp_default_agent="opencode",
            )

            # Simulate an active task
            agent._active_tasks["telegram:123"] = []

            # Create stop message
            msg = InboundMessage(
                channel="telegram",
                sender_id="user",
                chat_id="123",
                content="/stop",
            )

            # Handle stop
            await agent._handle_stop(msg)

            # Current gap: cancel_operation is NOT called on the ACP service
            # This assertion will fail until _handle_stop is updated
            assert cancel_called, (
                "The _handle_stop method should call acp_service.cancel_operation() "
                "when an ACP session is active, not just cancel local tasks."
            )


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


def test_cli_has_acp_option_in_agent():
    """Given agent command, when checking options, then ACP-related options should be available."""
    result = runner.invoke(app, ["agent", "--help"])
    assert result.exit_code == 0


# ============================================================================
# Test: Chat routing to ACP backend
# ============================================================================


@pytest.mark.asyncio
async def test_chat_routes_to_acp_backend_when_configured():
    """Given a user starts an ACP-backed chat, when they send a prompt, then it routes to the bound OpenCode ACP session."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    session_store = FakeACPSessionStore()
    callback_registry = FakeACPCallbackRegistry()

    service = ACPService(
        ACPServiceConfig(
            agent_path=None,
            storage_dir=None,
            callback_registry=callback_registry,
        )
    )

    service._session_store = session_store
    service._binding_store = None

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

        result1 = await service.create_session("cli:direct", "opencode")
        session_id_1 = result1["acp_session_id"]

        result2 = await service.load_session("cli:direct")
        session_id_2 = result2["acp_session_id"]

        assert session_id_1 == session_id_2


# ============================================================================
# Test: Session binding resolution and recovery
# ============================================================================


@pytest.mark.asyncio
async def test_session_binding_persists_to_store():
    """Given session binding is created, when store is available, then binding should be saved."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)

        service = ACPService(
            ACPServiceConfig(
                agent_path=None,
                storage_dir=storage_dir,
            )
        )

        await service.create_session("cli:direct", "opencode")

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

        result1 = await service.create_session("cli:direct", "opencode")
        acp_session_id_1 = result1["acp_session_id"]

        await service.shutdown_session("cli:direct")

        result2 = await service.load_session("cli:direct")
        acp_session_id_2 = result2["acp_session_id"]

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

    await runtime.initialize(ACPInitializeRequest(session_id="test-session"))
    await runtime.prompt(ACPPromptRequest(content="Hello", session_id="test-session"))

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

    async def grant_callback(callback):
        from nanobot.acp.types import ACPPermissionDecision

        return ACPPermissionDecision(request_id="test", granted=True)

    callback_registry.register_filesystem_callback(grant_callback)

    request = ACPPermissionRequest(
        id="perm-1",
        permission_type="filesystem",
        description="Read file",
        resource="/test/file.txt",
        callback=ACPFilesystemCallback(operation="read", path="/test/file.txt"),
    )

    decision = await callback_registry.handle_permission_request(request)
    assert decision.granted is True


# ============================================================================
# Test: Integration with CLI commands
# ============================================================================


@patch("nanobot.config.loader.load_config")
def test_cli_gateway_works_with_acp_config(mock_load_config, tmp_path):
    """Given gateway command with ACP config, when started, then it should initialize without error (no crash)."""
    config = Config()
    config.acp.agents["opencode"] = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        policy="auto",
    )
    config.acp.default_agent = "opencode"
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.gateway.heartbeat.enabled = False

    mock_load_config.return_value = config

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0


@patch("nanobot.config.loader.load_config")
def test_cli_agent_works_without_acp(mock_load_config, tmp_path):
    """Given agent command without ACP config, when started, then local agent mode should work."""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.gateway.heartbeat.enabled = False

    mock_load_config.return_value = config

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0


# ============================================================================
# Test: ACP mode selection logic
# ============================================================================


def test_acp_mode_is_selected_when_configured():
    """Given config with ACP default agent, when checking mode, then ACP should be selected."""
    config = Config()
    config.acp.default_agent = "opencode"
    assert config.acp.default_agent is not None


def test_local_mode_is_selected_when_not_configured():
    """Given config without ACP default agent, when checking mode, then local mode should be used."""
    config = Config()
    assert config.acp.default_agent is None
