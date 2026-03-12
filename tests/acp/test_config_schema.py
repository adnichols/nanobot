"""Tests for ACP configuration schema.

These tests verify that ACP configuration models are properly defined,
validated, and separate from MCP config.
"""

import pytest
from pydantic import ValidationError

from nanobot.config.schema import (
    ACPAgentDefinition,
    ACPConfig,
    ACPProcessSettings,
    ChannelsConfig,
    Config,
)


class TestACPAgentDefinition:
    """Tests for ACP agent definition model."""

    def test_agent_definition_with_required_fields(self):
        """Test that an agent definition with required fields validates."""
        agent = ACPAgentDefinition(
            id="opencode",
            command="opencode",
        )
        assert agent.id == "opencode"
        assert agent.command == "opencode"

    def test_agent_definition_with_all_fields(self):
        """Test that an agent definition with all fields validates."""
        agent = ACPAgentDefinition(
            id="opencode",
            command="opencode",
            args=["--agent"],
            env={"OPENCODE_API_KEY": "test-key"},
            cwd="/workspace",
            policy="ask",
            capabilities=["filesystem", "terminal", "webfetch"],
            max_tool_iterations=100,
            timeout=300,
        )
        assert agent.id == "opencode"
        assert agent.command == "opencode"
        assert agent.args == ["--agent"]
        assert agent.env == {"OPENCODE_API_KEY": "test-key"}
        assert agent.cwd == "/workspace"
        assert agent.policy == "ask"
        assert agent.capabilities == ["filesystem", "terminal", "webfetch"]
        assert agent.max_tool_iterations == 100
        assert agent.timeout == 300

    def test_agent_definition_defaults(self):
        """Test that agent definition has proper defaults."""
        agent = ACPAgentDefinition(
            id="test-agent",
            command="test-command",
        )
        assert agent.args == []
        assert agent.env == {}
        assert agent.cwd is None
        assert agent.policy == "auto"  # default permission policy
        assert agent.capabilities == []  # default capabilities
        assert agent.max_tool_iterations == 40  # default max iterations
        assert agent.timeout == 60  # default timeout seconds

    def test_agent_definition_id_validation(self):
        """Test that agent ID must be non-empty."""
        with pytest.raises(ValidationError):
            ACPAgentDefinition(id="", command="test")

    def test_agent_definition_command_validation(self):
        """Test that command must be non-empty."""
        with pytest.raises(ValidationError):
            ACPAgentDefinition(id="test", command="")

    def test_agent_definition_invalid_policy(self):
        """Test that invalid policy raises validation error."""
        with pytest.raises(ValidationError):
            ACPAgentDefinition(id="test", command="test", policy="invalid")


class TestACPConfig:
    """Tests for ACP configuration section."""

    def test_acp_config_empty(self):
        """Test that empty ACP config validates."""
        config = ACPConfig(agents={})
        assert config.agents == {}
        assert config.default_agent is None
        assert config.allow_local_fallback is False
        assert config.permission_policies == {}
        assert config.process_settings is not None

    def test_acp_config_with_agents(self):
        """Test ACP config with agent definitions."""
        config = ACPConfig(
            agents={
                "opencode": ACPAgentDefinition(id="opencode", command="opencode"),
                "claude": ACPAgentDefinition(id="claude", command="claude-code"),
            }
        )
        assert "opencode" in config.agents
        assert "claude" in config.agents

    def test_acp_config_default_agent(self):
        """Test default agent selection."""
        config = ACPConfig(
            agents={
                "opencode": ACPAgentDefinition(id="opencode", command="opencode"),
            },
            default_agent="opencode",
        )
        assert config.default_agent == "opencode"

    def test_acp_config_allow_local_fallback_override(self):
        """Test ACP fallback policy override."""
        config = ACPConfig(allow_local_fallback=True)
        assert config.allow_local_fallback is True

    def test_acp_config_permission_policies(self):
        """Test permission policy defaults."""
        config = ACPConfig(
            permission_policies={
                "filesystem": "ask",
                "terminal": "deny",
                "webfetch": "auto",
            }
        )
        assert config.permission_policies["filesystem"] == "ask"
        assert config.permission_policies["terminal"] == "deny"
        assert config.permission_policies["webfetch"] == "auto"

    def test_acp_config_process_settings(self):
        """Test process launch settings."""
        config = ACPConfig(
            process_settings=ACPProcessSettings(
                env={"MY_VAR": "value"},
                shell=True,
            )
        )
        assert config.process_settings.env["MY_VAR"] == "value"
        assert config.process_settings.shell is True


class TestConfigIntegration:
    """Tests for Config with ACP integration."""

    def test_config_has_acp_section(self):
        """Test that Config includes ACP configuration."""
        config = Config()
        assert hasattr(config, "acp")
        assert config.acp is not None

    def test_config_acp_defaults(self):
        """Test that Config has proper ACP defaults."""
        config = Config()
        assert config.acp.agents == {}
        assert config.acp.default_agent is None
        assert config.acp.allow_local_fallback is False

    def test_channels_progress_visibility_defaults(self):
        """Test that ACP progress visibility flags default to hidden."""
        channels = Config().channels
        assert channels.send_progress is True
        assert channels.send_tool_hints is False
        assert channels.acp_stream_content is False
        assert channels.acp_show_thinking is False
        assert channels.acp_show_tool_calls is False
        assert channels.acp_show_tool_results is False
        assert channels.acp_show_system is False

    def test_channels_allows_progress_respects_visibility_flags(self):
        """Test channel progress filtering across ACP-specific visibility kinds."""
        channels = ChannelsConfig(
            send_progress=True,
            send_tool_hints=False,
            acp_show_thinking=True,
            acp_show_tool_calls=False,
            acp_show_tool_results=True,
            acp_show_system=False,
        )

        assert channels.allows_progress(progress_kind="content") is True
        assert channels.allows_progress(progress_kind="thinking") is True
        assert channels.allows_progress(progress_kind="tool_call") is False
        assert channels.allows_progress(progress_kind="tool_result") is True
        assert channels.allows_progress(progress_kind="system") is False
        assert channels.allows_progress(tool_hint=True, progress_kind="tool_hint") is False

    def test_channels_allows_progress_short_circuits_when_progress_disabled(self):
        """Test disabling send_progress suppresses every non-tool-hint update."""
        channels = ChannelsConfig(
            send_progress=False,
            send_tool_hints=True,
            acp_show_thinking=True,
            acp_show_tool_calls=True,
            acp_show_tool_results=True,
            acp_show_system=True,
        )

        assert channels.allows_progress(progress_kind="content") is False
        assert channels.allows_progress(progress_kind="thinking") is False
        assert channels.allows_progress(progress_kind="tool_call") is False
        assert channels.allows_progress(progress_kind="tool_result") is False
        assert channels.allows_progress(progress_kind="system") is False
        assert channels.allows_progress(tool_hint=True, progress_kind="tool_hint") is True


    def test_config_acp_with_agents(self):
        """Test Config loads with ACP agents."""
        config = Config(
            acp={
                "agents": {
                    "opencode": {
                        "id": "opencode",
                        "command": "opencode",
                        "capabilities": ["filesystem", "terminal"],
                    }
                },
                "default_agent": "opencode",
            }
        )
        assert config.acp.agents["opencode"].id == "opencode"
        assert config.acp.default_agent == "opencode"
        assert "filesystem" in config.acp.agents["opencode"].capabilities
        assert "terminal" in config.acp.agents["opencode"].capabilities


class TestACPConfigSeparation:
    """Tests verifying ACP config is separate from MCP config."""

    def test_mcp_servers_not_in_acp(self):
        """Test that MCP server config is not in ACP section."""
        config = Config(
            tools={
                "mcp_servers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    }
                }
            }
        )
        # MCP config should be in tools section, not ACP
        assert hasattr(config.tools, "mcp_servers")
        assert "filesystem" in config.tools.mcp_servers
        # ACP section should not have MCP servers
        assert not hasattr(config.acp, "mcp_servers")

    def test_acp_is_independent_of_channels(self):
        """Test that ACP is independent of channel config."""
        config = Config(
            channels={"telegram": {"enabled": True, "token": "test-token"}},
            acp={"agents": {"opencode": {"id": "opencode", "command": "opencode"}}},
        )
        assert config.channels.telegram.enabled is True
        assert "opencode" in config.acp.agents
