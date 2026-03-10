"""OpenCode ACP Backend Adapter.

This module provides the OpenCode-specific implementation for the ACP agent
backend. It handles:
- Launching the OpenCode ACP subprocess with configured arguments
- Mapping MCP server configurations to ACP session setup
- Managing OpenCode-specific capabilities
- Handling load-session and session recovery

OpenCode-specific logic stays isolated here. Shared runtime and storage
modules remain free of OpenCode-specific imports.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Optional

from nanobot.acp.runtime import ACPCapabilities
from nanobot.acp.types import ACPSessionRecord
from nanobot.config.schema import ACPAgentDefinition, MCPServerConfig


class OpenCodeBackend:
    """OpenCode ACP backend adapter.

    This class provides the OpenCode-specific implementation for launching
    and managing ACP sessions with OpenCode as the agent backend.
    """

    def __init__(self, agent_config: ACPAgentDefinition) -> None:
        """Initialize the OpenCode backend.

        Args:
            agent_config: The OpenCode agent configuration.
        """
        self._agent_config = agent_config
        self._process: Optional[asyncio.subprocess.Process] = None
        self._running = False

    @property
    def agent_id(self) -> str:
        """Get the agent ID."""
        return self._agent_config.id

    def get_launch_command(self) -> list[str]:
        """Get the full launch command for starting the agent.

        Returns:
            List of command arguments.
        """
        return [self._agent_config.command] + self._agent_config.args

    def get_launch_env(self) -> dict[str, str]:
        """Get the environment variables for the agent process.

        Returns:
            Dictionary of environment variables (merged with current env).
        """
        # Start with current environment
        env = dict(os.environ)
        # Add/override with configured environment variables
        env.update(self._agent_config.env)
        return env

    def get_working_directory(self) -> Optional[Path]:
        """Get the working directory for the agent process.

        Returns:
            Path to working directory, or None if not configured.
        """
        if self._agent_config.cwd:
            return Path(self._agent_config.cwd)
        return None

    def build_initialize_payload(
        self,
        session_id: str,
        mcp_servers: Optional[dict[str, MCPServerConfig]] = None,
    ) -> dict[str, Any]:
        """Build the session initialize payload.

        Args:
            session_id: The session ID to initialize.
            mcp_servers: Optional MCP server configurations to pass through.

        Returns:
            The initialize payload dictionary.
        """
        payload: dict[str, Any] = {
            "session_id": session_id,
            "capabilities": {
                "declared": self._agent_config.capabilities,
            },
        }

        # Add working directory if configured
        if self._agent_config.cwd:
            payload["cwd"] = self._agent_config.cwd

        # Add MCP servers if provided
        if mcp_servers is not None:
            payload["mcp_servers"] = map_mcp_servers_to_payload(mcp_servers)

        return payload

    def build_load_session_payload(
        self,
        session_id: str,
        mcp_servers: Optional[dict[str, MCPServerConfig]] = None,
    ) -> dict[str, Any]:
        """Build the load session payload for resuming a session.

        Args:
            session_id: The session ID to load.
            mcp_servers: Optional MCP server configurations for reconnection.

        Returns:
            The load session payload dictionary.
        """
        payload: dict[str, Any] = {
            "session_id": session_id,
        }

        # Add MCP servers for reconnection
        if mcp_servers is not None:
            payload["mcp_servers"] = map_mcp_servers_to_payload(mcp_servers)

        return payload

    def build_recovery_payload(
        self,
        session_record: ACPSessionRecord,
        mcp_servers: Optional[dict[str, MCPServerConfig]] = None,
    ) -> dict[str, Any]:
        """Build the session recovery payload.

        This is used when resuming a persisted session, including
        state restoration and MCP server reconnection.

        Args:
            session_record: The persisted session record.
            mcp_servers: Optional MCP server configurations for reconnection.

        Returns:
            The recovery payload dictionary.
        """
        payload: dict[str, Any] = {
            "session_id": session_record.id,
            "state": session_record.state,
            "messages": session_record.messages,
            "created_at": session_record.created_at.isoformat(),
            "updated_at": session_record.updated_at.isoformat(),
        }

        # Add MCP servers for reconnection
        if mcp_servers is not None:
            payload["mcp_servers"] = map_mcp_servers_to_payload(mcp_servers)

        # Preserve any metadata from the session
        if session_record.metadata:
            payload["metadata"] = session_record.metadata

        return payload

    def get_capabilities(self) -> ACPCapabilities:
        """Get the capabilities advertised by this backend.

        Returns:
            ACPCapabilities object with backend capabilities.
        """
        return ACPCapabilities(
            tools=["read", "write", "bash", "grep", "glob", "webfetch", "memory"],
            permissions=["filesystem", "terminal", "webfetch", "memory"],
            supports_streaming=True,
            supports_session_persistence=True,
            metadata={
                "declared": self._agent_config.capabilities,
                "policy": self._agent_config.policy,
                "max_tool_iterations": self._agent_config.max_tool_iterations,
            },
        )

    async def start(self) -> None:
        """Start the OpenCode ACP subprocess.

        Raises:
            RuntimeError: If the process fails to start.
            FileNotFoundError: If the command is not found.
        """
        command = self.get_launch_command()
        env = self.get_launch_env()
        cwd = self.get_working_directory()

        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(cwd) if cwd else None,
            )
            self._running = True
        except FileNotFoundError as e:
            raise FileNotFoundError(f"OpenCode command not found: {command[0]}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to start OpenCode: {e}") from e

    async def stop(self) -> None:
        """Stop the OpenCode ACP subprocess."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

        self._running = False
        self._process = None

    def is_running(self) -> bool:
        """Check if the backend process is running.

        Returns:
            True if running, False otherwise.
        """
        return self._running and self._process is not None and self._process.returncode is None


def map_mcp_servers_to_payload(
    mcp_servers: dict[str, MCPServerConfig],
) -> dict[str, dict[str, Any]]:
    """Map MCP server configurations to ACP session setup format.

    This function transforms nanobot's MCP server configuration into
    the format expected by the ACP backend during session initialization.

    Args:
        mcp_servers: Dictionary of MCP server name to configuration.

    Returns:
        Dictionary mapping server names to their payload format.
    """
    mapped: dict[str, dict[str, Any]] = {}

    for name, config in mcp_servers.items():
        server_entry: dict[str, Any] = {}

        # Handle stdio-based servers
        if config.command:
            server_entry["type"] = "stdio"
            server_entry["command"] = config.command
            server_entry["args"] = config.args
            if config.env:
                server_entry["env"] = config.env

        # Handle HTTP-based servers
        if config.url:
            server_entry["type"] = "http"
            server_entry["url"] = config.url
            if config.headers:
                server_entry["headers"] = config.headers

        # Common fields
        server_entry["tool_timeout"] = config.tool_timeout

        mapped[name] = server_entry

    return mapped
