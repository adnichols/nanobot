"""ACP update accumulation and translation.

This module provides:
- ACPUpdateAccumulator: Consumes ACPUpdateEvent stream and accumulates updates
- Integration with subscribe_updates() hook from ACP-03
- Translation of raw ACP updates to accumulated state
- Clean interface for the rendering layer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Optional

from nanobot.acp.interfaces import ACPUpdateSink
from nanobot.acp.types import (
    ACPRenderedUpdate,
    ACPStreamChunk,
    ACPStreamChunkType,
    ACPUpdateEvent,
)

ProgressUpdateCallback = Callable[["ACPProgressUpdate"], Awaitable[None]]


@dataclass
class AccumulatedUpdate:
    """An accumulated update with its content and metadata."""

    event_type: str
    timestamp: datetime
    content: str
    correlation_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ACPProgressVisibility:
    """Visibility controls for ACP progress categories."""

    show_thinking: bool = False
    show_tool_calls: bool = False
    show_tool_results: bool = False
    show_system: bool = False

    def allows(self, kind: str) -> bool:
        """Return whether a progress kind should be emitted."""
        if kind == "thinking":
            return self.show_thinking
        if kind == "tool_call":
            return self.show_tool_calls
        if kind == "tool_result":
            return self.show_tool_results
        if kind == "system":
            return self.show_system
        return True


@dataclass(frozen=True)
class ACPProgressUpdate:
    """A user-visible ACP progress update after filtering and classification."""

    kind: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ACPUpdateAccumulator:
    """Accumulates ACP update events by session/prompt correlation.

    This class:
    - Consumes ACPUpdateEvent from the subscribe_updates() hook
    - Accumulates updates by session and correlation ID
    - Handles tool updates, plan updates, and message chunks
    - Exposes a clean interface for the rendering layer
    """

    def __init__(self, upstream_sink: Optional[ACPUpdateSink] = None):
        """Initialize the accumulator.

        Args:
            upstream_sink: Optional upstream sink to forward events to.
        """
        self._upstream_sink = upstream_sink
        self._subscribers: list[ACPUpdateSink] = []
        self._accumulated: dict[str, list[AccumulatedUpdate]] = {}

        # Track correlation to session mapping
        self._correlation_sessions: dict[str, str] = {}

    def subscribe(self, sink: ACPUpdateSink) -> None:
        """Subscribe a sink to receive accumulated updates.

        Args:
            sink: The update sink to receive events.
        """
        self._subscribers.append(sink)

    async def receive_update(self, event: ACPUpdateEvent) -> None:
        """Receive an update event and accumulate it.

        Args:
            event: The update event to process.
        """
        # Forward to upstream if configured
        if self._upstream_sink:
            await self._upstream_sink.send_update(event)

        # Track correlation to session mapping
        if event.correlation_id:
            session_id = event.payload.get("session_id", event.correlation_id)
            self._correlation_sessions[event.correlation_id] = session_id

        # Accumulate the event
        key = self._get_accumulation_key(event)
        if key not in self._accumulated:
            self._accumulated[key] = []

        # Convert to accumulated update
        accumulated = self._convert_to_accumulated(event)
        self._accumulated[key].append(accumulated)

        # Notify subscribers
        for subscriber in self._subscribers:
            try:
                await subscriber.send_update(event)
            except Exception:
                # Log but don't fail on subscriber errors
                pass

    async def receive_chunk(
        self, chunk: ACPStreamChunk, correlation_id: Optional[str] = None
    ) -> None:
        """Receive a stream chunk and accumulate it.

        Args:
            chunk: The stream chunk to process.
            correlation_id: Optional correlation ID for the chunk.
        """
        # Forward to upstream if configured
        if self._upstream_sink:
            await self._upstream_sink.stream_chunk(chunk)

        # Convert chunk to accumulated update
        content = chunk.content or ""

        # Handle different chunk types
        if chunk.type == ACPStreamChunkType.CONTENT_DELTA:
            event_type = "content_chunk"
        elif chunk.type == ACPStreamChunkType.TOOL_USE_START:
            event_type = "tool_use_start"
            content = f"Using tool: {chunk.tool_name}"
        elif chunk.type == ACPStreamChunkType.TOOL_USE_END:
            event_type = "tool_use_end"
            content = f"Tool complete: {chunk.tool_name}"
        elif chunk.type == ACPStreamChunkType.TOOL_RESULT_START:
            event_type = "tool_result_start"
        elif chunk.type == ACPStreamChunkType.TOOL_RESULT_END:
            event_type = "tool_result_end"
            content = chunk.tool_result_content or ""
        elif chunk.type == ACPStreamChunkType.DONE:
            event_type = "prompt_end"
        elif chunk.type == ACPStreamChunkType.ERROR:
            event_type = "error"
            content = chunk.error or "Unknown error"
        else:
            event_type = "unknown_chunk"

        accumulated = AccumulatedUpdate(
            event_type=event_type,
            timestamp=datetime.now(UTC),
            content=content,
            correlation_id=correlation_id,
            metadata={
                "tool_name": chunk.tool_name,
                "tool_input": chunk.tool_input,
                "tool_result_id": chunk.tool_result_id,
            },
        )

        # Accumulate under correlation key
        if correlation_id:
            key = correlation_id
            if key not in self._accumulated:
                self._accumulated[key] = []
            self._accumulated[key].append(accumulated)

        # Notify subscribers
        for subscriber in self._subscribers:
            try:
                await subscriber.stream_chunk(chunk)
            except Exception:
                pass

    def progress_for_event(
        self,
        event: ACPUpdateEvent,
        visibility: ACPProgressVisibility | None = None,
    ) -> ACPProgressUpdate | None:
        """Convert an event to a filtered, user-visible progress update."""
        kind = self._progress_kind_for_event(event)
        visible = visibility or ACPProgressVisibility()
        if not visible.allows(kind):
            return None

        content = self._generate_content(event).strip()
        if not content:
            return None

        return ACPProgressUpdate(kind=kind, content=content, metadata=event.payload)

    def _get_accumulation_key(self, event: ACPUpdateEvent) -> str:
        """Get the key for accumulating this event.

        Args:
            event: The update event.

        Returns:
            A string key for accumulation.
        """
        # Use correlation_id if available, otherwise use session_id from payload
        if event.correlation_id:
            return event.correlation_id
        return event.payload.get("session_id", "unknown")

    def _convert_to_accumulated(self, event: ACPUpdateEvent) -> AccumulatedUpdate:
        """Convert an ACPUpdateEvent to an AccumulatedUpdate.

        Args:
            event: The update event.

        Returns:
            The accumulated update.
        """
        # Generate content based on event type
        content = self._generate_content(event)

        return AccumulatedUpdate(
            event_type=event.event_type,
            timestamp=event.timestamp,
            content=content,
            correlation_id=event.correlation_id,
            metadata=event.payload,
        )

    @staticmethod
    def _progress_kind_for_event(event: ACPUpdateEvent) -> str:
        """Classify an event into a gateway-level progress visibility bucket."""
        event_type = event.event_type
        if event_type == "agent_thought_chunk":
            return "thinking"
        if event_type in {"tool_use_start", "tool_use_end"}:
            return "tool_call"
        if event_type in {"tool_result", "tool_result_start", "tool_result_end"}:
            return "tool_result"
        if event_type in {"content_chunk", "prompt_start", "prompt_end", "error"}:
            return "content"
        return "system"

    def _generate_content(self, event: ACPUpdateEvent) -> str:
        """Generate display content for an event.

        Args:
            event: The update event.

        Returns:
            Display content string.
        """
        event_type = event.event_type
        payload = event.payload

        if event_type == "initialize":
            return "Agent initialized"
        elif event_type == "new_session":
            return f"New session created: {payload.get('session_id', 'unknown')}"
        elif event_type == "session_loaded":
            return f"Session loaded: {payload.get('session_id', 'unknown')}"
        elif event_type == "prompt_start":
            content = payload.get("content", "")
            return f"Processing: {content[:50]}..."
        elif event_type == "prompt_end":
            return "Response complete"
        elif event_type == "content_chunk":
            return payload.get("content", "")
        elif event_type == "agent_thought_chunk":
            thought = payload.get("content") or payload.get("thought", "")
            return str(thought)
        elif event_type == "tool_use_start":
            tool_name = payload.get("tool_name", "unknown")
            return f"Using tool: {tool_name}"
        elif event_type == "tool_use_end":
            tool_name = payload.get("tool_name", "unknown")
            return f"Tool finished: {tool_name}"
        elif event_type == "tool_result":
            tool_name = payload.get("tool_name", "unknown")
            content = payload.get("content", "")
            return f"{tool_name}: {content[:100]}"
        elif event_type == "tool_result_start":
            tool_name = payload.get("tool_name", "unknown")
            return f"{tool_name}: running"
        elif event_type == "tool_result_end":
            tool_name = payload.get("tool_name", "unknown")
            content = payload.get("content", "")
            return f"{tool_name}: {content[:100]}" if content else f"{tool_name}: complete"
        elif event_type == "permission_request":
            perm_type = payload.get("permission_type", "unknown")
            desc = payload.get("description", "")
            return f"Permission request ({perm_type}): {desc}"
        elif event_type == "permission_decision":
            granted = payload.get("granted", False)
            reason = payload.get("reason", "")
            return f"Permission {'approved' if granted else 'denied'}: {reason}"
        elif event_type == "cancel":
            return "Operation cancelled"
        elif event_type == "shutdown":
            return "Agent shutting down"
        elif event_type == "system_notice":
            return str(payload.get("content", "")).strip()
        else:
            return f"Event: {event_type}"

    def get_accumulated(self, correlation_id: str) -> list[AccumulatedUpdate]:
        """Get accumulated updates for a correlation ID.

        Args:
            correlation_id: The correlation ID to get updates for.

        Returns:
            List of accumulated updates.
        """
        return self._accumulated.get(correlation_id, [])

    def get_session_for_correlation(self, correlation_id: str) -> Optional[str]:
        """Get the session ID for a correlation ID.

        Args:
            correlation_id: The correlation ID.

        Returns:
            The session ID, if known.
        """
        return self._correlation_sessions.get(correlation_id)

    def clear_accumulated(self, correlation_id: Optional[str] = None) -> None:
        """Clear accumulated updates.

        Args:
            correlation_id: Optional specific correlation ID to clear.
                          If None, clears all.
        """
        if correlation_id:
            self._accumulated.pop(correlation_id, None)
            self._correlation_sessions.pop(correlation_id, None)
        else:
            self._accumulated.clear()
            self._correlation_sessions.clear()


class ACPDirectUpdateSink:
    """A direct update sink that forwards to an accumulator.

    This can be used as an ACPUpdateSink to feed into the accumulator.
    """

    def __init__(self, accumulator: ACPUpdateAccumulator):
        """Initialize the direct update sink.

        Args:
            accumulator: The accumulator to forward to.
        """
        self._accumulator = accumulator

    async def send_update(self, event: ACPUpdateEvent) -> None:
        """Send an update event to the accumulator."""
        await self._accumulator.receive_update(event)

    async def send_rendered(self, update: ACPRenderedUpdate) -> None:
        """Send a rendered update (not used in direct sink)."""
        pass

    async def stream_chunk(self, chunk: ACPStreamChunk) -> None:
        """Stream a chunk to the accumulator."""
        await self._accumulator.receive_chunk(chunk)


class ACPFilteringProgressSink:
    """ACP update sink that filters runtime events into user-visible progress callbacks."""

    def __init__(
        self,
        accumulator: ACPUpdateAccumulator,
        visibility: ACPProgressVisibility,
        on_progress: ProgressUpdateCallback,
    ):
        self._accumulator = accumulator
        self._visibility = visibility
        self._on_progress = on_progress

    async def send_update(self, event: ACPUpdateEvent) -> None:
        """Accumulate an update and forward it when visibility permits."""
        await self._accumulator.receive_update(event)
        progress = self._accumulator.progress_for_event(event, visibility=self._visibility)
        if progress is not None:
            await self._on_progress(progress)

    async def send_rendered(self, update: ACPRenderedUpdate) -> None:
        """Rendered updates are not used by this sink."""
        pass

    async def stream_chunk(self, chunk: ACPStreamChunk) -> None:
        """Accumulate a stream chunk for downstream final-answer assembly."""
        await self._accumulator.receive_chunk(chunk)
