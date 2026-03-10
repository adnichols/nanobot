"""Fake ACP agent harness for testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Optional

from nanobot.acp.interfaces import (
    ACPCallbackRegistry,
    ACPSessionStore,
    ACPUpdateSink,
)
from nanobot.acp.types import (
    ACPCancelRequest,
    ACPFilesystemCallback,
    ACPInitializeRequest,
    ACPLoadSessionRequest,
    ACPPermissionDecision,
    ACPPermissionRequest,
    ACPPromptRequest,
    ACPRenderedUpdate,
    ACPSessionRecord,
    ACPStreamChunk,
    ACPStreamChunkType,
    ACPTerminalCallback,
    ACPUpdateEvent,
)


class FakeACPSessionStore:
    """Fake implementation of ACPSessionStore for testing."""

    def __init__(self):
        self._sessions: dict[str, ACPSessionRecord] = {}

    async def save(self, session: ACPSessionRecord) -> None:
        self._sessions[session.id] = session

    async def load(self, session_id: str) -> Optional[ACPSessionRecord]:
        return self._sessions.get(session_id)

    async def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def list_sessions(self) -> list[ACPSessionRecord]:
        return list(self._sessions.values())


class FakeACPCallbackRegistry:
    """Fake implementation of ACPCallbackRegistry for testing."""

    def __init__(self):
        self._filesystem_handler: Optional[Callable] = None
        self._terminal_handler: Optional[Callable] = None
        self._webfetch_handler: Optional[Callable] = None

    def register_filesystem_callback(
        self, handler: Callable[[ACPFilesystemCallback], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._filesystem_handler = handler

    def register_terminal_callback(
        self, handler: Callable[[ACPTerminalCallback], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._terminal_handler = handler

    def register_webfetch_callback(
        self, handler: Callable[[dict[str, Any]], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._webfetch_handler = handler

    async def handle_permission_request(
        self, request: ACPPermissionRequest
    ) -> ACPPermissionDecision:
        if request.permission_type == "filesystem" and self._filesystem_handler:
            return await self._filesystem_handler(request.callback)
        elif request.permission_type == "terminal" and self._terminal_handler:
            return await self._terminal_handler(request.callback)
        elif request.permission_type == "webfetch" and self._webfetch_handler:
            return await self._webfetch_handler(request.callback)
        return ACPPermissionDecision(
            request_id=request.id,
            granted=False,
            reason="No handler registered for permission type",
        )


class FakeACPUpdateSink:
    """Fake implementation of ACPUpdateSink for testing."""

    def __init__(self):
        self.updates: list[ACPUpdateEvent] = []
        self.rendered: list[ACPRenderedUpdate] = []
        self.stream_chunks: list[Any] = []

    async def send_update(self, event: ACPUpdateEvent) -> None:
        self.updates.append(event)

    async def send_rendered(self, update: ACPRenderedUpdate) -> None:
        self.rendered.append(update)

    async def stream_chunk(self, chunk: Any) -> None:
        self.stream_chunks.append(chunk)


@dataclass
class FakeACPAgentRuntime:
    """Fake ACP agent runtime for testing.

    This simulates the agent protocol behavior without requiring a real backend.
    It can emit updates, handle permissions, and manage sessions.
    """

    session_store: Optional[ACPSessionStore] = None
    callback_registry: Optional[ACPCallbackRegistry] = None
    update_sinks: list[ACPUpdateSink] = field(default_factory=list)

    _initialized: bool = field(default=False, init=False)
    _cancelled: bool = field(default=False, init=False)
    _current_session_id: Optional[str] = field(default=None, init=False)

    def subscribe_updates(self, sink: ACPUpdateSink) -> None:
        """Subscribe to update events from the agent."""
        self.update_sinks.append(sink)

    async def initialize(self, request: ACPInitializeRequest) -> dict[str, Any]:
        """Simulate agent initialization.

        This should fail initially (NotImplementedError) until real implementation.
        """
        if not self._initialized:
            # Emit initialization event
            event = ACPUpdateEvent(
                event_type="initialize",
                timestamp=datetime.now(UTC),
                payload={"session_id": request.session_id},
            )
            for sink in self.update_sinks:
                await sink.send_update(event)

        self._initialized = True
        self._current_session_id = request.session_id
        return {"status": "initialized", "session_id": request.session_id}

    async def prompt(self, request: ACPPromptRequest) -> list[ACPStreamChunk]:
        """Simulate prompt response with streaming chunks.

        This should fail initially (NotImplementedError) until real implementation.
        """
        if not self._initialized:
            raise RuntimeError("Agent not initialized")

        if self._cancelled:
            return []

        # Emit prompt start event
        event = ACPUpdateEvent(
            event_type="prompt_start",
            timestamp=datetime.now(UTC),
            payload={"content": request.content},
            correlation_id=request.session_id,
        )
        for sink in self.update_sinks:
            await sink.send_update(event)

        # Stream chunks
        chunks = []
        chunk = ACPStreamChunk(
            type=ACPStreamChunkType.CONTENT_DELTA, content=f"Response to: {request.content[:50]}..."
        )
        chunks.append(chunk)
        for sink in self.update_sinks:
            await sink.stream_chunk(chunk)

        # Emit prompt end event
        event = ACPUpdateEvent(
            event_type="prompt_end",
            timestamp=datetime.now(UTC),
            payload={"session_id": request.session_id},
            correlation_id=request.session_id,
        )
        for sink in self.update_sinks:
            await sink.send_update(event)

        return chunks

    async def cancel(self, request: ACPCancelRequest) -> None:
        """Simulate cancellation."""
        self._cancelled = True
        event = ACPUpdateEvent(
            event_type="cancel",
            timestamp=datetime.now(UTC),
            payload={"session_id": request.session_id},
        )
        for sink in self.update_sinks:
            await sink.send_update(event)

    async def load_session(self, request: ACPLoadSessionRequest) -> dict[str, Any]:
        """Load a persisted session.

        This should fail initially (NotImplementedError) until real implementation.
        """
        if self.session_store is None:
            raise NotImplementedError("No session store configured")

        session = await self.session_store.load(request.session_id)
        if session is None:
            raise ValueError(f"Session not found: {request.session_id}")

        self._initialized = True
        self._current_session_id = request.session_id

        event = ACPUpdateEvent(
            event_type="session_loaded",
            timestamp=datetime.now(UTC),
            payload={"session_id": request.session_id},
        )
        for sink in self.update_sinks:
            await sink.send_update(event)

        return {"status": "loaded", "session": session.to_dict()}

    async def handle_permission(self, request: ACPPermissionRequest) -> ACPPermissionDecision:
        """Handle a permission request.

        This should fail initially (NotImplementedError) until real implementation.
        """
        if self.callback_registry is None:
            raise NotImplementedError("No callback registry configured")

        return await self.callback_registry.handle_permission_request(request)

    async def handle_filesystem(self, callback: ACPFilesystemCallback) -> ACPPermissionDecision:
        """Dispatch a filesystem callback through the fake callback registry."""
        request = ACPPermissionRequest(
            id=callback.metadata.get("request_id", "fake-fs-request"),
            permission_type="filesystem",
            description=f"Filesystem {callback.operation}: {callback.path}",
            resource=callback.path,
            callback=callback,
            correlation_id=callback.metadata.get("correlation_id"),
        )
        return await self.handle_permission(request)

    async def handle_terminal(self, callback: ACPTerminalCallback) -> ACPPermissionDecision:
        """Dispatch a terminal callback through the fake callback registry."""
        request = ACPPermissionRequest(
            id="fake-terminal-request",
            permission_type="terminal",
            description=f"Terminal command: {callback.command}",
            resource=callback.command,
            callback=callback,
        )
        return await self.handle_permission(request)
