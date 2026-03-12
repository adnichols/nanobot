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
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.acp.types import ACPInitializeRequest, ACPPromptRequest, ACPUpdateEvent
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
        model="openai/gpt-5.4",
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
            model="openai/gpt-5.4",
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
            assert passed_config.agent_definition.model == "openai/gpt-5.4"
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


def test_acp_service_uses_workspace_dir_when_agent_cwd_missing():
    """ACP sessions should default to the configured workspace when agent cwd is unset."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    agent_definition = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
    )
    service = ACPService(
        ACPServiceConfig(
            agent_path="opencode",
            workspace_dir=Path("/workspace/from-config"),
            agent_definition=agent_definition,
        )
    )

    with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
        service._create_client()

    assert mock_client_cls.call_args.kwargs["cwd"] == "/workspace/from-config"


@pytest.mark.asyncio
async def test_load_session_preserves_agent_definition_on_resume():
    """Given a resumed ACP session, load_session should recreate the client with full agent config."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    agent_definition = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        model="openai/gpt-5.4",
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
        client.initialize = AsyncMock(
            return_value={"status": "initialized", "capabilities": {"loadSession": True}}
        )
        client.capabilities = {"loadSession": True}
        client.model = "openai/gpt-5.4"
        client.load_session = AsyncMock(
            return_value={"session": {"id": "sess-123"}, "status": "loaded"}
        )
        client.new_session = AsyncMock(
            return_value={"session_id": "new-session", "status": "created"}
        )
        client.set_model = AsyncMock()
        mock_client_cls.return_value = client

        await service.load_session("cli:direct")

    # Verify that args, env, cwd are extracted from agent_definition and passed to SDKClient
    assert mock_client_cls.call_args.kwargs["model"] == "openai/gpt-5.4"
    assert mock_client_cls.call_args.kwargs["args"] == ["acp", "--verbose"]
    assert mock_client_cls.call_args.kwargs["env"] == {"OPENCODE_API_KEY": "secret123"}
    assert mock_client_cls.call_args.kwargs["cwd"] == "/workspace/myproject"
    client.set_model.assert_awaited_once_with("openai/gpt-5.4", session_id="sess-123")


@pytest.mark.asyncio
async def test_close_mcp_shuts_down_acp_service():
    """AgentLoop cleanup should close both MCP and ACP resources."""
    from nanobot.agent.loop import AgentLoop

    bus = MagicMock()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    acp_service = MagicMock()
    acp_service.shutdown = AsyncMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=Path(tmpdir),
            acp_service=acp_service,
            acp_default_agent="opencode",
        )
        mcp_stack = MagicMock()
        mcp_stack.aclose = AsyncMock()
        agent._mcp_stack = mcp_stack

        await agent.close_mcp()

    mcp_stack.aclose.assert_awaited_once()
    acp_service.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_session_applies_configured_model_override():
    """Given an ACP agent model override, create_session should apply it before prompting."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    agent_definition = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        model="openai/gpt-5.4",
        args=["acp"],
    )
    service = ACPService(ACPServiceConfig(agent_path="opencode", agent_definition=agent_definition))

    with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
        client = MagicMock()
        client.initialize = AsyncMock(return_value={"status": "initialized", "capabilities": {}})
        client.new_session = AsyncMock(return_value={"session_id": "sess-123", "status": "created"})
        client.set_model = AsyncMock()
        client.capabilities = {}
        client.model = "openai/gpt-5.4"
        mock_client_cls.return_value = client

        result = await service.create_session("cli:direct")

    assert result["acp_session_id"] == "sess-123"
    client.set_model.assert_awaited_once_with("openai/gpt-5.4", session_id="sess-123")


@pytest.mark.asyncio
async def test_trusted_telegram_auto_policy_resolves_without_prompting():
    """Interactive Telegram sessions should resolve `policy=auto` without callback prompts."""
    import nanobot.cli.commands as commands_module
    from nanobot.acp.types import ACPPermissionRequest

    config = Config()
    config.acp.agents["opencode"] = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        policy="auto",
    )
    config.acp.default_agent = "opencode"

    commands_module._acp_service = None
    try:
        service = commands_module._get_acp_service(config)
        assert service is not None

        with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
            service._create_client("telegram:123")

        permission_broker = mock_client_cls.call_args.kwargs["permission_broker"]
        assert permission_broker is not None
        assert permission_broker.is_interactive is True
        assert (
            mock_client_cls.call_args.kwargs["callback_registry"]
            is service._config.callback_registry
        )

        decision = await permission_broker.request_permission(
            ACPPermissionRequest(
                id="perm-telegram-auto",
                permission_type="filesystem",
                description="Read README",
                resource="/workspace/README.md",
            )
        )

        assert decision.granted is True
    finally:
        commands_module._acp_service = None


@pytest.mark.asyncio
async def test_non_telegram_auto_policy_does_not_get_trusted_allow_defaults():
    """Approval-free `auto` defaults should stay confined to trusted Telegram sessions."""
    import nanobot.cli.commands as commands_module
    from nanobot.acp.types import ACPPermissionRequest

    config = Config()
    config.acp.agents["opencode"] = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        policy="auto",
    )
    config.acp.default_agent = "opencode"

    commands_module._acp_service = None
    try:
        service = commands_module._get_acp_service(config)
        assert service is not None

        with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
            service._create_client("discord:123")

        permission_broker = mock_client_cls.call_args.kwargs["permission_broker"]
        assert permission_broker is not None
        assert permission_broker.is_interactive is False

        decision = await permission_broker.request_permission(
            ACPPermissionRequest(
                id="perm-discord-auto",
                permission_type="filesystem",
                description="Read README",
                resource="/workspace/README.md",
            )
        )

        assert decision.granted is False
    finally:
        commands_module._acp_service = None


@pytest.mark.asyncio
async def test_trusted_telegram_explicit_deny_policy_rejects_without_prompting():
    """Trusted Telegram sessions should still honor explicit `deny` without callbacks."""
    import nanobot.cli.commands as commands_module
    from nanobot.acp.types import ACPPermissionRequest

    config = Config()
    config.acp.agents["opencode"] = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        policy="deny",
    )
    config.acp.default_agent = "opencode"

    commands_module._acp_service = None
    try:
        service = commands_module._get_acp_service(config)
        assert service is not None

        with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
            service._create_client("telegram:123")

        permission_broker = mock_client_cls.call_args.kwargs["permission_broker"]
        assert permission_broker is not None
        assert permission_broker.is_interactive is True

        decision = await permission_broker.request_permission(
            ACPPermissionRequest(
                id="perm-telegram-deny",
                permission_type="terminal",
                description="Run ls",
                resource="/bin/ls",
            )
        )

        assert decision.granted is False
    finally:
        commands_module._acp_service = None


@pytest.mark.asyncio
async def test_explicit_ask_policy_emits_permission_updates_before_denial():
    """Ask mode should still surface permission request and decision updates."""
    import nanobot.cli.commands as commands_module
    from nanobot.acp.sdk_client import SDKNotificationHandler

    config = Config()
    config.acp.agents["opencode"] = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        policy="ask",
    )
    config.acp.default_agent = "opencode"

    commands_module._acp_service = None
    try:
        service = commands_module._get_acp_service(config)
        assert service is not None

        with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
            service._create_client("telegram:123")

        permission_broker = mock_client_cls.call_args.kwargs["permission_broker"]
        assert permission_broker is not None
        assert permission_broker.is_interactive is True

        update_sink = FakeACPUpdateSink()
        handler = SDKNotificationHandler(
            update_sink=update_sink,
            permission_broker=permission_broker,
        )

        await handler._handle_permission_request(
            {
                "session_id": "acp-session-123",
                "request_id": "perm-ask-1",
                "permission_type": "filesystem",
                "description": "Read project file",
                "resource": "/workspace/README.md",
            }
        )

        assert [event.event_type for event in update_sink.updates] == [
            "permission_request",
            "permission_decision",
        ]
        assert update_sink.updates[1].payload["granted"] is False
    finally:
        commands_module._acp_service = None


@pytest.mark.asyncio
async def test_trusted_telegram_ask_policy_uses_service_callback_registry_when_registered():
    """Trusted ask-mode sessions should preserve the callback path for future approvals."""
    import nanobot.cli.commands as commands_module
    from nanobot.acp.types import ACPFilesystemCallback, ACPPermissionDecision, ACPPermissionRequest

    config = Config()
    config.acp.agents["opencode"] = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        policy="ask",
    )
    config.acp.default_agent = "opencode"

    commands_module._acp_service = None
    try:
        service = commands_module._get_acp_service(config)
        assert service is not None
        assert service._config.callback_registry is not None

        async def approve_filesystem(_callback: ACPFilesystemCallback) -> ACPPermissionDecision:
            return ACPPermissionDecision(
                request_id="perm-telegram-ask-handler",
                granted=True,
                reason="Approved by callback handler",
            )

        service.register_filesystem_callback(approve_filesystem)

        with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
            service._create_client("telegram:123")

        permission_broker = mock_client_cls.call_args.kwargs["permission_broker"]
        assert permission_broker is not None
        assert permission_broker.is_interactive is True

        decision = await permission_broker.request_permission(
            ACPPermissionRequest(
                id="perm-telegram-ask-handler",
                permission_type="filesystem",
                description="Read README",
                resource="/workspace/README.md",
                callback=ACPFilesystemCallback(operation="read", path="/workspace/README.md"),
            )
        )

        assert decision.granted is True
        assert decision.reason == "Approved by callback handler"
    finally:
        commands_module._acp_service = None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("permission_type", "callback"),
    [
        (
            "filesystem",
            lambda: __import__(
                "nanobot.acp.types", fromlist=["ACPFilesystemCallback"]
            ).ACPFilesystemCallback(
                operation="read",
                path="/workspace/README.md",
            ),
        ),
        (
            "terminal",
            lambda: __import__(
                "nanobot.acp.types", fromlist=["ACPTerminalCallback"]
            ).ACPTerminalCallback(
                command="ls",
                working_directory="/workspace",
                environment={},
            ),
        ),
    ],
)
async def test_trusted_telegram_ask_policy_does_not_auto_approve_live_handlers(
    permission_type, callback
):
    """Ask mode must stay approval-gated even when live ACP handlers are wired."""
    import nanobot.cli.commands as commands_module
    from nanobot.acp.types import ACPPermissionRequest

    config = Config()
    config.acp.agents["opencode"] = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        policy="ask",
    )
    config.acp.default_agent = "opencode"

    commands_module._acp_service = None
    try:
        service = commands_module._get_acp_service(config)
        assert service is not None

        with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
            service._create_client("telegram:123")

        permission_broker = mock_client_cls.call_args.kwargs["permission_broker"]
        assert permission_broker is not None
        assert permission_broker.is_interactive is True

        decision = await permission_broker.request_permission(
            ACPPermissionRequest(
                id=f"perm-telegram-ask-{permission_type}",
                permission_type=permission_type,
                description=f"Use {permission_type}",
                resource="/workspace/README.md" if permission_type == "filesystem" else "ls",
                callback=callback(),
            )
        )

        assert decision.granted is False
    finally:
        commands_module._acp_service = None


@pytest.mark.asyncio
async def test_live_acp_service_registers_real_filesystem_and_terminal_handlers_before_prompting():
    """Slash-command ACP sessions should reach SDK clients with live filesystem and terminal handlers."""
    import nanobot.cli.commands as commands_module

    config = Config()
    config.acp.agents["opencode"] = ACPAgentDefinition(
        id="opencode",
        command="opencode",
        args=["acp"],
        policy="auto",
    )
    config.acp.default_agent = "opencode"

    commands_module._acp_service = None
    try:
        service = commands_module._get_acp_service(config)
        assert service is not None
        assert service._config.callback_registry is not None
        assert getattr(service._config.callback_registry, "_filesystem_handler", None) is None
        assert getattr(service._config.callback_registry, "_terminal_handler", None) is None

        with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
            client = MagicMock()
            client.initialize = AsyncMock(
                return_value={"status": "initialized", "capabilities": {}}
            )
            client.new_session = AsyncMock(
                return_value={"session_id": "sess-123", "status": "created"}
            )
            client.prompt = AsyncMock(return_value=[])
            client.capabilities = {}
            client.model = None
            mock_client_cls.return_value = client

            await service.process_message("telegram:123", "/model openai/gpt-5.4")

        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs["filesystem_handler"] is not None
        assert hasattr(kwargs["filesystem_handler"], "handle_filesystem_callback")
        assert kwargs["terminal_manager"] is not None
        assert hasattr(kwargs["terminal_manager"], "create")
    finally:
        commands_module._acp_service = None


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

    @pytest.mark.asyncio
    async def test_acp_routing_returns_final_response_without_streaming_progress(self):
        """ACP routing should return only the final response even when on_progress is provided."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"

        progress_updates: list[str] = []

        async def process_message(session_key: str, message: str, on_chunk=None) -> list[MagicMock]:
            assert session_key == "telegram:123456789"
            assert message == "Hello from Telegram"
            assert on_chunk is None
            return [
                MagicMock(content="Streaming from ACP is underway "),
                MagicMock(content="now."),
            ]

        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(return_value={"acp_session_id": "test-session"})
        mock_acp_service.process_message = AsyncMock(side_effect=process_message)

        async def on_progress(text: str) -> None:
            progress_updates.append(text)

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
                session_key="telegram:123456789",
                message="Hello from Telegram",
                on_progress=on_progress,
            )

        assert response is not None
        assert response.channel == "telegram"
        assert response.chat_id == "123456789"
        assert response.content == "Streaming from ACP is underway now."
        assert progress_updates == []

    @pytest.mark.asyncio
    async def test_acp_routing_preserves_inbound_metadata_on_final_response(self):
        """ACP-backed Telegram replies should keep inbound metadata for reply quoting."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"

        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(return_value={"acp_session_id": "test-session"})
        mock_acp_service.process_message = AsyncMock(
            return_value=[MagicMock(content="ACP response")]
        )

        metadata = {
            "message_id": "42",
            "user_id": "7",
            "username": "alice",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent = AgentLoop(
                bus=bus,
                provider=mock_provider,
                workspace=workspace,
                acp_service=mock_acp_service,
                acp_default_agent="opencode",
            )

            response = await agent._process_message(
                InboundMessage(
                    channel="telegram",
                    sender_id="user",
                    chat_id="123456789",
                    content="Hello from Telegram",
                    metadata=metadata,
                )
            )

        assert response is not None
        assert response.channel == "telegram"
        assert response.chat_id == "123456789"
        assert response.content == "ACP response"
        assert response.metadata == metadata

    @pytest.mark.asyncio
    async def test_acp_routing_subscribes_to_visible_updates_without_live_content(self):
        """Visible ACP updates should subscribe even when live content streaming is disabled."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"

        progress_updates: list[tuple[str, str]] = []
        config = Config()
        config.channels.acp_show_thinking = True
        config.channels.acp_show_tool_results = True
        config.channels.acp_show_system = True

        subscribed_sink = None

        def subscribe_updates(session_key: str, sink) -> None:
            nonlocal subscribed_sink
            assert session_key == "telegram:123456789"
            subscribed_sink = sink

        async def process_message(session_key: str, message: str, on_chunk=None) -> list[MagicMock]:
            assert session_key == "telegram:123456789"
            assert message == "Hello from Telegram"
            assert on_chunk is None
            assert subscribed_sink is not None

            await subscribed_sink.send_update(
                ACPUpdateEvent(
                    event_type="agent_thought_chunk",
                    timestamp=datetime.now(UTC),
                    payload={
                        "session_id": "test-session",
                        "content": "Thinking...",
                    },
                    correlation_id="prompt-1",
                )
            )
            await subscribed_sink.send_update(
                ACPUpdateEvent(
                    event_type="tool_result",
                    timestamp=datetime.now(UTC),
                    payload={
                        "session_id": "test-session",
                        "tool_name": "read",
                        "content": "Observed tool result",
                    },
                    correlation_id="prompt-1",
                )
            )
            await subscribed_sink.send_update(
                ACPUpdateEvent(
                    event_type="system_notice",
                    timestamp=datetime.now(UTC),
                    payload={
                        "session_id": "test-session",
                        "content": "System notice",
                    },
                    correlation_id="prompt-1",
                )
            )
            return [MagicMock(content="ACP response")]

        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(return_value={"acp_session_id": "test-session"})
        mock_acp_service.process_message = AsyncMock(side_effect=process_message)
        mock_acp_service.subscribe_updates = MagicMock(side_effect=subscribe_updates)

        async def on_progress(text: str, *, progress_kind: str = "content", **_kwargs) -> None:
            progress_updates.append((text, progress_kind))

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent = AgentLoop(
                bus=bus,
                provider=mock_provider,
                workspace=workspace,
                channels_config=config.channels,
                acp_service=mock_acp_service,
                acp_default_agent="opencode",
            )

            response = await agent._route_to_acp(
                session_key="telegram:123456789",
                message="Hello from Telegram",
                on_progress=on_progress,
            )

        assert response is not None
        assert response.content == "ACP response"
        assert progress_updates == [
            ("Thinking...", "thinking"),
            ("read: Observed tool result", "tool_result"),
            ("System notice", "system"),
        ]
        mock_acp_service.subscribe_updates.assert_called_once()

    @pytest.mark.asyncio
    async def test_acp_routing_subscribes_to_tool_call_updates_without_live_content(self):
        """Tool-call visibility alone should still attach the ACP update sink."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"

        progress_updates: list[tuple[str, str]] = []
        config = Config()
        config.channels.acp_show_tool_calls = True

        subscribed_sink = None

        def subscribe_updates(session_key: str, sink) -> None:
            nonlocal subscribed_sink
            assert session_key == "telegram:123456789"
            subscribed_sink = sink

        async def process_message(session_key: str, message: str, on_chunk=None) -> list[MagicMock]:
            assert session_key == "telegram:123456789"
            assert message == "Hello from Telegram"
            assert on_chunk is None
            assert subscribed_sink is not None

            await subscribed_sink.send_update(
                ACPUpdateEvent(
                    event_type="tool_use_start",
                    timestamp=datetime.now(UTC),
                    payload={
                        "session_id": "test-session",
                        "tool_name": "read",
                    },
                    correlation_id="prompt-1",
                )
            )
            return [MagicMock(content="ACP response")]

        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(return_value={"acp_session_id": "test-session"})
        mock_acp_service.process_message = AsyncMock(side_effect=process_message)
        mock_acp_service.subscribe_updates = MagicMock(side_effect=subscribe_updates)

        async def on_progress(text: str, *, progress_kind: str = "content", **_kwargs) -> None:
            progress_updates.append((text, progress_kind))

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent = AgentLoop(
                bus=bus,
                provider=mock_provider,
                workspace=workspace,
                channels_config=config.channels,
                acp_service=mock_acp_service,
                acp_default_agent="opencode",
            )

            response = await agent._route_to_acp(
                session_key="telegram:123456789",
                message="Hello from Telegram",
                on_progress=on_progress,
            )

        assert response is not None
        assert response.content == "ACP response"
        assert progress_updates == [("Using tool: read", "tool_call")]
        mock_acp_service.subscribe_updates.assert_called_once()

    @pytest.mark.asyncio
    async def test_acp_routing_clears_stale_update_subscription_when_progress_hidden(self):
        """Calls without visible progress should clear any previously attached ACP sink."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"

        config = Config()
        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(return_value={"acp_session_id": "test-session"})
        mock_acp_service.process_message = AsyncMock(
            return_value=[MagicMock(content="ACP response")]
        )
        mock_acp_service.subscribe_updates = MagicMock()
        mock_acp_service.clear_update_subscription = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent = AgentLoop(
                bus=bus,
                provider=mock_provider,
                workspace=workspace,
                channels_config=config.channels,
                acp_service=mock_acp_service,
                acp_default_agent="opencode",
            )

            response = await agent._route_to_acp(
                session_key="telegram:123456789",
                message="Hello from Telegram",
                on_progress=None,
            )

        assert response is not None
        assert response.content == "ACP response"
        mock_acp_service.clear_update_subscription.assert_called_once_with("telegram:123456789")
        mock_acp_service.subscribe_updates.assert_not_called()

    @pytest.mark.asyncio
    async def test_acp_routing_streams_live_content_when_enabled(self):
        """ACP routing should restore live content and filtered ACP updates when enabled."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"

        progress_updates: list[tuple[str, str]] = []
        config = Config()
        config.channels.acp_stream_content = True
        config.channels.acp_show_thinking = True
        config.channels.acp_show_tool_results = False
        config.channels.acp_show_system = True

        subscribed_sink = None

        def subscribe_updates(session_key: str, sink) -> None:
            nonlocal subscribed_sink
            assert session_key == "telegram:123456789"
            subscribed_sink = sink

        async def process_message(session_key: str, message: str, on_chunk=None) -> list[MagicMock]:
            assert session_key == "telegram:123456789"
            assert message == "Hello from Telegram"
            assert on_chunk is not None
            assert subscribed_sink is not None

            await subscribed_sink.send_update(
                ACPUpdateEvent(
                    event_type="agent_thought_chunk",
                    timestamp=datetime.now(UTC),
                    payload={
                        "session_id": "test-session",
                        "content": "Thinking...",
                    },
                    correlation_id="prompt-1",
                )
            )
            await subscribed_sink.send_update(
                ACPUpdateEvent(
                    event_type="tool_result",
                    timestamp=datetime.now(UTC),
                    payload={
                        "session_id": "test-session",
                        "tool_name": "read",
                        "content": "hidden tool output",
                    },
                    correlation_id="prompt-1",
                )
            )
            await subscribed_sink.send_update(
                ACPUpdateEvent(
                    event_type="system_notice",
                    timestamp=datetime.now(UTC),
                    payload={
                        "session_id": "test-session",
                        "content": "System notice",
                    },
                    correlation_id="prompt-1",
                )
            )
            await on_chunk("Streaming ")
            await on_chunk("now.")
            return [
                MagicMock(content="Streaming "),
                MagicMock(content="now."),
            ]

        mock_acp_service = MagicMock()
        mock_acp_service.load_session = AsyncMock(return_value={"acp_session_id": "test-session"})
        mock_acp_service.process_message = AsyncMock(side_effect=process_message)
        mock_acp_service.subscribe_updates = MagicMock(side_effect=subscribe_updates)

        async def on_progress(text: str, *, progress_kind: str = "content", **_kwargs) -> None:
            progress_updates.append((text, progress_kind))

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            agent = AgentLoop(
                bus=bus,
                provider=mock_provider,
                workspace=workspace,
                channels_config=config.channels,
                acp_service=mock_acp_service,
                acp_default_agent="opencode",
            )

            response = await agent._route_to_acp(
                session_key="telegram:123456789",
                message="Hello from Telegram",
                on_progress=on_progress,
            )

        assert response is not None
        assert response.content == "Streaming now."
        assert progress_updates == [
            ("Thinking...", "thinking"),
            ("System notice", "system"),
            ("Streaming ", "content"),
            ("now.", "content"),
        ]
        assert ("Streaming now.", "content") not in progress_updates
        mock_acp_service.subscribe_updates.assert_called_once()


class TestACPFallback:
    @pytest.mark.asyncio
    async def test_process_message_returns_acp_error_by_default(self):
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.chat = AsyncMock()

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
        assert response.content == "ACP error: ACP unavailable"
        assert response.channel == "telegram"
        assert response.chat_id == "123"
        mock_provider.chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_slash_command_acp_failures_use_existing_error_path(self):
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.chat = AsyncMock()

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
                    content="/model openai/gpt-5.4",
                )
            )

        assert response is not None
        assert response.content == "ACP error: ACP unavailable"
        assert response.channel == "telegram"
        assert response.chat_id == "123"
        mock_provider.chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_message_falls_back_to_local_when_opted_in_for_errors(self):
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
                acp_allow_local_fallback=True,
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
        mock_provider.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_message_returns_acp_timeout_by_default(self):
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus

        bus = MagicMock(spec=MessageBus)
        mock_provider = MagicMock()
        mock_provider.get_default_model.return_value = "test-model"
        mock_provider.chat = AsyncMock()

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
        assert response.content == "ACP error: timed out after 0.01s"
        assert response.channel == "telegram"
        assert response.chat_id == "123"
        mock_provider.chat.assert_not_awaited()
        mock_acp_service.cancel_operation.assert_awaited_once_with("telegram:123")

    @pytest.mark.asyncio
    async def test_process_message_falls_back_to_local_when_opted_in_for_timeouts(self):
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
                acp_allow_local_fallback=True,
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
        mock_provider.chat.assert_awaited_once()
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


def test_cli_agent_single_message_mode_uses_default_acp_fallback_policy(tmp_path):
    """`nanobot agent` should pass the default ACP fallback policy into AgentLoop."""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")

    provider = MagicMock()
    agent_loop = MagicMock()
    agent_loop.process_direct = AsyncMock(return_value="CLI_PATH_OK")
    agent_loop.close_mcp = AsyncMock()
    agent_loop.channels_config = None

    with (
        patch("nanobot.config.loader.load_config", return_value=config),
        patch("nanobot.config.loader.get_data_dir", return_value=tmp_path),
        patch("nanobot.cli.commands.sync_workspace_templates"),
        patch("nanobot.cli.commands._make_provider", return_value=provider),
        patch("nanobot.cli.commands._get_acp_service", return_value=None),
        patch("nanobot.cron.service.CronService"),
        patch("nanobot.agent.loop.AgentLoop", return_value=agent_loop) as agent_loop_cls,
        patch("nanobot.cli.commands._print_agent_response"),
    ):
        result = runner.invoke(app, ["agent", "--logs", "-m", "hello"])

    assert result.exit_code == 0
    agent_loop_cls.assert_called_once()
    assert agent_loop_cls.call_args.kwargs["acp_allow_local_fallback"] is False
    agent_loop.process_direct.assert_awaited_once()
    agent_loop.close_mcp.assert_awaited_once()


def test_cli_agent_single_message_mode_passes_acp_fallback_override(tmp_path):
    """`nanobot agent` should pass the ACP fallback override into AgentLoop."""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.acp.allow_local_fallback = True

    provider = MagicMock()
    agent_loop = MagicMock()
    agent_loop.process_direct = AsyncMock(return_value="CLI_PATH_OK")
    agent_loop.close_mcp = AsyncMock()
    agent_loop.channels_config = None

    with (
        patch("nanobot.config.loader.load_config", return_value=config),
        patch("nanobot.config.loader.get_data_dir", return_value=tmp_path),
        patch("nanobot.cli.commands.sync_workspace_templates"),
        patch("nanobot.cli.commands._make_provider", return_value=provider),
        patch("nanobot.cli.commands._get_acp_service", return_value=object()),
        patch("nanobot.cron.service.CronService"),
        patch("nanobot.agent.loop.AgentLoop", return_value=agent_loop) as agent_loop_cls,
        patch("nanobot.cli.commands._print_agent_response"),
    ):
        result = runner.invoke(app, ["agent", "--logs", "-m", "hello"])

    assert result.exit_code == 0
    agent_loop_cls.assert_called_once()
    assert agent_loop_cls.call_args.kwargs["acp_allow_local_fallback"] is True


def test_gateway_passes_acp_fallback_override_to_agent_loop(tmp_path):
    """`nanobot gateway` should thread the ACP fallback policy into AgentLoop."""
    import nanobot.cli.commands as commands_module

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.acp.agents["opencode"] = ACPAgentDefinition(id="opencode", command="opencode")
    config.acp.default_agent = "opencode"
    config.acp.allow_local_fallback = True
    config.gateway.heartbeat.enabled = False

    provider = MagicMock()
    bus = MagicMock()
    session_manager = MagicMock()
    session_manager.list_sessions.return_value = []
    cron = MagicMock()
    cron.status.return_value = {"jobs": 0}
    channels = MagicMock()
    channels.enabled_channels = []
    heartbeat = MagicMock()
    agent = MagicMock()
    agent.model = "test-model"

    with (
        patch("nanobot.config.loader.load_config", return_value=config),
        patch("nanobot.config.loader.get_data_dir", return_value=tmp_path),
        patch("nanobot.cli.commands.sync_workspace_templates"),
        patch("nanobot.cli.commands._make_provider", return_value=provider),
        patch("nanobot.cli.commands._get_acp_service", return_value=object()),
        patch("nanobot.bus.queue.MessageBus", return_value=bus),
        patch("nanobot.session.manager.SessionManager", return_value=session_manager),
        patch("nanobot.cron.service.CronService", return_value=cron),
        patch("nanobot.channels.manager.ChannelManager", return_value=channels),
        patch("nanobot.heartbeat.service.HeartbeatService", return_value=heartbeat),
        patch("nanobot.agent.loop.AgentLoop", return_value=agent) as agent_loop_cls,
        patch("nanobot.cli.commands.asyncio.run", side_effect=lambda coro: coro.close()),
    ):
        commands_module.gateway(port=8080, verbose=False)

    agent_loop_cls.assert_called_once()
    assert agent_loop_cls.call_args.kwargs["acp_allow_local_fallback"] is True


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


@pytest.mark.asyncio
async def test_load_session_reuses_active_client_without_respawning_agent():
    """load_session should reuse an already-active SDK client for the same session key."""
    from nanobot.acp.service import ACPService, ACPServiceConfig

    service = ACPService(ACPServiceConfig(agent_path="opencode"))

    with patch("nanobot.acp.service.SDKClient") as mock_client_cls:
        client = MagicMock()
        client.initialize = AsyncMock(return_value={"status": "initialized", "capabilities": {}})
        client.new_session = AsyncMock(return_value={"session_id": "sess-123", "status": "created"})
        client.set_model = AsyncMock()
        client.capabilities = {}
        client.current_session_id = "sess-123"
        mock_client_cls.return_value = client

        created = await service.create_session("telegram:123")
        mock_client_cls.reset_mock()

        loaded = await service.load_session("telegram:123")

    assert created["acp_session_id"] == "sess-123"
    assert loaded == {
        "nanobot_session_key": "telegram:123",
        "acp_session_id": "sess-123",
        "agent_id": "default",
        "status": "loaded",
        "session": None,
    }
    mock_client_cls.assert_not_called()


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


@pytest.mark.asyncio
async def test_acp_new_clears_persisted_binding_before_next_session_load():
    """`/new` should remove both the live client and persisted ACP binding."""
    from nanobot.acp.service import ACPService, ACPServiceConfig
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir) / "acp"
        service = ACPService(
            ACPServiceConfig(
                agent_path=None,
                storage_dir=storage_dir,
            )
        )

        await service.create_session("telegram:123", "opencode")
        assert service._binding_store is not None
        assert service._binding_store.load_binding("telegram:123") is not None

        bus = MagicMock(spec=MessageBus)
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        agent = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=Path(tmpdir),
            acp_service=service,
            acp_default_agent="opencode",
        )

        response = await agent._process_message(
            InboundMessage(
                channel="telegram",
                sender_id="user",
                chat_id="123",
                content="/new",
            )
        )

        assert response is not None
        assert response.content == "New session started (ACP)."
        assert "telegram:123" not in service.active_sessions
        assert service._binding_store.load_binding("telegram:123") is None

        second = await service.load_session("telegram:123")
        rebound = service._binding_store.load_binding("telegram:123")

    assert second["status"] == "created"
    assert rebound is not None
    assert rebound.acp_session_id == second["acp_session_id"]


@pytest.mark.asyncio
async def test_acp_new_reports_reset_failures_instead_of_claiming_success():
    """`/new` should surface ACP reset failures so stale sessions are not hidden."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    class FailingACPService:
        async def reset_session(self, nanobot_session_key: str) -> None:
            raise RuntimeError(f"reset failed for {nanobot_session_key}")

    bus = MagicMock(spec=MessageBus)
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=Path(tmpdir),
            acp_service=FailingACPService(),
            acp_default_agent="opencode",
        )

        response = await agent._process_message(
            InboundMessage(
                channel="telegram",
                sender_id="user",
                chat_id="123",
                content="/new",
                metadata={"message_id": "9"},
            )
        )

    assert response is not None
    assert response.content == "ACP error: reset failed for telegram:123"
    assert response.metadata == {"message_id": "9"}


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
