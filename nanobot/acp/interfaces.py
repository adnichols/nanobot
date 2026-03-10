"""Importable interfaces for ACP runtime components.

These interfaces define the contract between the ACP runtime and the
surrounding system (session storage, callbacks, update sinks, etc.).
They are designed to be importable by downstream tracks without reaching
into implementation files.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Protocol

from nanobot.acp.types import (
    ACPFilesystemCallback,
    ACPPermissionDecision,
    ACPPermissionRequest,
    ACPRenderedUpdate,
    ACPSessionRecord,
    ACPTerminalCallback,
    ACPUpdateEvent,
)


class ACPSessionStore(Protocol):
    """Protocol for persisting and retrieving ACP sessions."""

    async def save(self, session: ACPSessionRecord) -> None:
        """Save a session record."""
        ...

    async def load(self, session_id: str) -> Optional[ACPSessionRecord]:
        """Load a session by ID. Returns None if not found."""
        ...

    async def delete(self, session_id: str) -> None:
        """Delete a session by ID."""
        ...

    async def list_sessions(self) -> list[ACPSessionRecord]:
        """List all available sessions."""
        ...


class ACPCallbackRegistry(Protocol):
    """Registry for handling ACP callbacks (filesystem, terminal, etc.)."""

    def register_filesystem_callback(
        self, handler: Callable[[ACPFilesystemCallback], Awaitable[ACPPermissionDecision]]
    ) -> None:
        """Register a handler for filesystem permission requests."""
        ...

    def register_terminal_callback(
        self, handler: Callable[[ACPTerminalCallback], Awaitable[ACPPermissionDecision]]
    ) -> None:
        """Register a handler for terminal permission requests."""
        ...

    def register_webfetch_callback(
        self, handler: Callable[[dict[str, Any]], Awaitable[ACPPermissionDecision]]
    ) -> None:
        """Register a handler for web fetch permission requests."""
        ...

    async def handle_permission_request(
        self, request: ACPPermissionRequest
    ) -> ACPPermissionDecision:
        """Handle a permission request by routing to the appropriate handler."""
        ...


class ACPUpdateSink(Protocol):
    """Protocol for receiving update events from the ACP runtime."""

    async def send_update(self, event: ACPUpdateEvent) -> None:
        """Send an update event to the sink."""
        ...

    async def send_rendered(self, update: ACPRenderedUpdate) -> None:
        """Send a rendered update to the sink."""
        ...

    async def stream_chunk(self, chunk: Any) -> None:
        """Stream a chunk of content (for prompt streaming)."""
        ...


class ACPRenderEvent(Protocol):
    """Protocol for renderable events from the ACP runtime."""

    @property
    def event_type(self) -> str:
        """The type of render event."""
        ...

    @property
    def content(self) -> str:
        """The content to render."""
        ...

    @property
    def metadata(self) -> dict[str, Any]:
        """Additional metadata for rendering."""
        ...


class ACPAgentRuntime(Protocol):
    """Protocol for the ACP agent runtime itself."""

    async def initialize(self, request: Any) -> dict[str, Any]:
        """Initialize the agent with the given request."""
        ...

    async def prompt(self, request: Any) -> Any:
        """Send a prompt to the agent and get a response."""
        ...

    async def cancel(self, request: Any) -> None:
        """Cancel an ongoing operation."""
        ...

    async def load_session(self, request: Any) -> dict[str, Any]:
        """Load a persisted session for resumption."""
        ...

    async def handle_filesystem(self, callback: ACPFilesystemCallback) -> ACPPermissionDecision:
        """Dispatch a filesystem callback through the registered ACP handler."""
        ...

    async def handle_terminal(self, callback: ACPTerminalCallback) -> ACPPermissionDecision:
        """Dispatch a terminal callback through the registered ACP handler."""
        ...

    def subscribe_updates(self, sink: ACPUpdateSink) -> None:
        """Subscribe to update events from the agent."""
        ...


# Type aliases for commonly used callback signatures
FilesystemHandler = Callable[[ACPFilesystemCallback], Awaitable[ACPPermissionDecision]]
TerminalHandler = Callable[[ACPTerminalCallback], Awaitable[ACPPermissionDecision]]
WebfetchHandler = Callable[[dict[str, Any]], Awaitable[ACPPermissionDecision]]
