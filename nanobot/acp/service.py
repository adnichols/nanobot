"""ACP service interface.

This module provides a high-level service interface that integrates ACP
runtime with nanobot's session management, CLI, and chat functionality.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from nanobot.acp.client import ACPClient
from nanobot.acp.interfaces import ACPCallbackRegistry, ACPSessionStore, ACPUpdateSink
from nanobot.acp.store import ACPSessionBindingStore
from nanobot.acp.types import (
    ACPStreamChunk,
)


@dataclass
class ACPServiceConfig:
    """Configuration for the ACP service."""

    agent_path: Optional[str] = None
    storage_dir: Optional[Path] = None
    callback_registry: Optional[ACPCallbackRegistry] = None


class ACPService:
    """High-level ACP service interface.

    Integrates with nanobot's session management and provides a bridge
    between CLI/chat and ACP runtime.
    """

    def __init__(self, config: Optional[ACPServiceConfig] = None):
        """Initialize the ACP service.

        Args:
            config: Service configuration.
        """
        self._config = config or ACPServiceConfig()
        self._session_store: Optional[ACPSessionStore] = None
        self._binding_store: Optional[ACPSessionBindingStore] = None
        self._clients: dict[str, ACPClient] = {}

        # Initialize stores if storage dir is provided
        if self._config.storage_dir:
            from nanobot.acp.store import ACPFileSessionStore

            self._session_store = ACPFileSessionStore(self._config.storage_dir / "sessions")
            self._binding_store = ACPSessionBindingStore(self._config.storage_dir / "bindings")

    async def create_session(
        self,
        nanobot_session_key: str,
        agent_id: str = "default",
    ) -> dict[str, Any]:
        """Create a new ACP session bound to a nanobot session.

        Args:
            nanobot_session_key: The nanobot session key (e.g., "telegram:12345").
            agent_id: The ACP agent ID to use.

        Returns:
            Dict containing session information.
        """
        # Create a new client for this session
        client = ACPClient(
            agent_path=self._config.agent_path,
            session_store=self._session_store,
            callback_registry=self._config.callback_registry,
        )

        # Initialize and create session
        await client.initialize()
        result = await client.create_session()

        acp_session_id = result.get("session_id")

        # Store the binding
        if self._binding_store:
            from nanobot.acp.store import ACPSessionBinding

            binding = ACPSessionBinding(
                nanobot_session_key=nanobot_session_key,
                acp_agent_id=agent_id,
                acp_session_id=acp_session_id,
            )
            self._binding_store.save_binding(binding)

        # Track the client
        self._clients[nanobot_session_key] = client

        return {
            "nanobot_session_key": nanobot_session_key,
            "acp_session_id": acp_session_id,
            "agent_id": agent_id,
            "status": "created",
        }

    async def load_session(self, nanobot_session_key: str) -> dict[str, Any]:
        """Load an existing ACP session for a nanobot session.

        Args:
            nanobot_session_key: The nanobot session key.

        Returns:
            Dict containing session information.
        """
        # Check for existing binding
        binding = None
        if self._binding_store:
            binding = self._binding_store.load_binding(nanobot_session_key)

        if not binding:
            # No existing session - create a new one
            return await self.create_session(nanobot_session_key)

        # Create client and load the session
        client = ACPClient(
            agent_path=self._config.agent_path,
            session_store=self._session_store,
            callback_registry=self._config.callback_registry,
        )

        await client.initialize()
        result = await client.load_session(binding.acp_session_id)

        # Track the client
        self._clients[nanobot_session_key] = client

        return {
            "nanobot_session_key": nanobot_session_key,
            "acp_session_id": binding.acp_session_id,
            "agent_id": binding.acp_agent_id,
            "status": "loaded",
            "session": result.get("session"),
        }

    async def process_message(
        self,
        nanobot_session_key: str,
        message: str,
    ) -> list[ACPStreamChunk]:
        """Process an incoming chat message through ACP.

        Args:
            nanobot_session_key: The nanobot session key.
            message: The message content.

        Returns:
            List of response stream chunks.
        """
        # Ensure we have a session
        if nanobot_session_key not in self._clients:
            await self.load_session(nanobot_session_key)

        client = self._clients[nanobot_session_key]
        return await client.prompt(message)

    async def cancel_operation(self, nanobot_session_key: str) -> None:
        """Cancel an ongoing operation for a session.

        Args:
            nanobot_session_key: The nanobot session key.
        """
        if nanobot_session_key in self._clients:
            await self._clients[nanobot_session_key].cancel()

    def subscribe_updates(
        self,
        nanobot_session_key: str,
        sink: ACPUpdateSink,
    ) -> None:
        """Subscribe to updates for a session.

        Args:
            nanobot_session_key: The nanobot session key.
            sink: The update sink.
        """
        if nanobot_session_key in self._clients:
            self._clients[nanobot_session_key].subscribe_updates(sink)

    def register_filesystem_callback(self, handler: Any) -> None:
        """Register a filesystem permission handler for all sessions.

        Args:
            handler: Async handler for filesystem callbacks.
        """
        for client in self._clients.values():
            client.register_filesystem_callback(handler)

    def register_terminal_callback(self, handler: Any) -> None:
        """Register a terminal permission handler for all sessions.

        Args:
            handler: Async handler for terminal callbacks.
        """
        for client in self._clients.values():
            client.register_terminal_callback(handler)

    async def shutdown_session(self, nanobot_session_key: str) -> None:
        """Shutdown a specific session.

        Args:
            nanobot_session_key: The nanobot session key.
        """
        if nanobot_session_key in self._clients:
            await self._clients[nanobot_session_key].shutdown()
            del self._clients[nanobot_session_key]

    async def shutdown(self) -> None:
        """Shutdown all sessions and cleanup resources."""
        for client in self._clients.values():
            await client.shutdown()
        self._clients.clear()

    def get_session_info(self, nanobot_session_key: str) -> Optional[dict[str, Any]]:
        """Get information about a session.

        Args:
            nanobot_session_key: The nanobot session key.

        Returns:
            Session info dict or None if not found.
        """
        client = self._clients.get(nanobot_session_key)
        if not client:
            return None

        binding = None
        if self._binding_store:
            binding = self._binding_store.load_binding(nanobot_session_key)

        return {
            "nanobot_session_key": nanobot_session_key,
            "acp_session_id": client.current_session_id,
            "is_initialized": client.is_initialized,
            "capabilities": client.capabilities,
            "binding": binding.to_dict() if binding else None,
        }

    @property
    def active_sessions(self) -> list[str]:
        """Get list of active session keys."""
        return list(self._clients.keys())
