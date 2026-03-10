"""ACP client wrapper.

This module provides a high-level client wrapper around the ACP agent runtime.
It handles connection lifecycle and exposes a clean public API for interacting
with ACP agents.
"""

from __future__ import annotations

from typing import Any, Optional

from nanobot.acp.interfaces import ACPCallbackRegistry, ACPSessionStore, ACPUpdateSink
from nanobot.acp.runtime import ACPAgentRuntime
from nanobot.acp.types import (
    ACPCancelRequest,
    ACPInitializeRequest,
    ACPLoadSessionRequest,
    ACPPromptRequest,
    ACPStreamChunk,
)


class ACPClient:
    """ACP client wrapper.

    Provides a clean public API for interacting with ACP agents.
    Handles connection lifecycle and session management.
    """

    def __init__(
        self,
        agent_path: Optional[str] = None,
        session_store: Optional[ACPSessionStore] = None,
        callback_registry: Optional[ACPCallbackRegistry] = None,
    ):
        """Initialize the ACP client.

        Args:
            agent_path: Path to the ACP agent executable.
            session_store: Optional session store for persistence.
            callback_registry: Optional callback registry for permissions.
        """
        self._agent_path = agent_path
        self._session_store = session_store
        self._callback_registry = callback_registry
        self._runtime: Optional[ACPAgentRuntime] = None
        self._current_session_id: Optional[str] = None

    @property
    def runtime(self) -> Optional[ACPAgentRuntime]:
        """Get the underlying runtime."""
        return self._runtime

    async def initialize(self, session_id: Optional[str] = None) -> dict[str, Any]:
        """Initialize the client and agent runtime.

        Args:
            session_id: Optional session ID to use.

        Returns:
            Dict containing initialization status and capabilities.
        """
        self._runtime = ACPAgentRuntime(
            agent_path=self._agent_path,
            session_store=self._session_store,
            callback_registry=self._callback_registry,
        )

        request = ACPInitializeRequest(
            session_id=session_id or "default-session",
            system_prompt="You are a helpful AI assistant.",
        )

        result = await self._runtime.initialize(request)
        self._current_session_id = result.get("session_id")
        return result

    async def create_session(self) -> dict[str, Any]:
        """Create a new ACP session.

        Returns:
            Dict containing the new session ID.
        """
        if self._runtime is None:
            await self.initialize()

        result = await self._runtime.new_session()
        self._current_session_id = result.get("session_id")
        return result

    async def load_session(self, session_id: str) -> dict[str, Any]:
        """Load an existing ACP session.

        Args:
            session_id: The session ID to load.

        Returns:
            Dict containing session status and data.
        """
        if self._runtime is None:
            await self.initialize()

        request = ACPLoadSessionRequest(session_id=session_id)
        result = await self._runtime.load_session(request)
        self._current_session_id = session_id
        return result

    async def prompt(self, content: str, session_id: Optional[str] = None) -> list[ACPStreamChunk]:
        """Send a prompt to the ACP agent.

        Args:
            content: The prompt content.
            session_id: Optional session ID (uses current session if not provided).

        Returns:
            List of stream chunks from the agent.
        """
        if self._runtime is None:
            await self.initialize()

        target_session = session_id or self._current_session_id or "default-session"
        request = ACPPromptRequest(content=content, session_id=target_session)
        return await self._runtime.prompt(request)

    async def cancel(self, session_id: Optional[str] = None) -> None:
        """Cancel an ongoing prompt operation.

        Args:
            session_id: Optional session ID (uses current session if not provided).
        """
        if self._runtime is None:
            return

        target_session = session_id or self._current_session_id or "default-session"
        request = ACPCancelRequest(session_id=target_session)
        await self._runtime.cancel(request)

    def subscribe_updates(self, sink: ACPUpdateSink) -> None:
        """Subscribe to update events.

        Args:
            sink: The update sink to receive events.
        """
        if self._runtime:
            self._runtime.subscribe_updates(sink)

    def register_filesystem_callback(self, handler: Any) -> None:
        """Register a filesystem permission handler.

        Args:
            handler: Async handler for filesystem callbacks.
        """
        if self._runtime:
            self._runtime.register_filesystem_callback(handler)

    def register_terminal_callback(self, handler: Any) -> None:
        """Register a terminal permission handler.

        Args:
            handler: Async handler for terminal callbacks.
        """
        if self._runtime:
            self._runtime.register_terminal_callback(handler)

    async def shutdown(self) -> None:
        """Shutdown the client and runtime."""
        if self._runtime:
            await self._runtime.shutdown()
            self._runtime = None

    @property
    def is_initialized(self) -> bool:
        """Check if the client is initialized."""
        return self._runtime is not None and self._runtime.is_initialized

    @property
    def current_session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return self._current_session_id

    @property
    def capabilities(self) -> Optional[Any]:
        """Get the agent capabilities."""
        if self._runtime:
            return self._runtime.capabilities
        return None
