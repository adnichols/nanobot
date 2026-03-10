"""ACP update rendering to user-visible progress.

This module provides:
- ACPRenderer: Converts accumulated updates to channel-safe progress messages
- Handles tool updates, plan updates, message chunks
- Implements deterministic duplicate suppression
- Renders final answer coherently after many chunks
- Reuses nanobot's OutboundMessage events on the message bus
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from nanobot.acp.permissions import ACPPermissionBroker
from nanobot.acp.types import (
    ACPRenderedUpdate,
    ACPStreamChunk,
    ACPStreamChunkType,
    ACPUpdateEvent,
)
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus


@dataclass
class RenderedPayload:
    """A deterministic representation of a rendered update payload."""

    update_type: str
    content: str
    correlation_id: Optional[str] = None
    session_id: Optional[str] = None

    def to_hashable(self) -> tuple:
        """Convert to a hashable representation for deduplication."""
        return (
            self.update_type,
            self.content,
            self.correlation_id or "",
            self.session_id or "",
        )


class ACPRenderer:
    """Renders ACP updates to user-visible progress.

    This class:
    - Converts accumulated updates to channel-safe progress messages
    - Handles tool updates, plan updates, message chunks
    - Preserves semantics without flattening important details
    - Implements deterministic duplicate suppression
    - Renders final answer coherently after many chunks
    - Reuses nanobot's OutboundMessage events on the message bus
    """

    def __init__(
        self,
        message_bus: MessageBus,
        permission_broker: Optional[ACPPermissionBroker] = None,
        channel: str = "acp",
    ):
        """Initialize the renderer.

        Args:
            message_bus: The message bus to publish outbound messages to.
            permission_broker: Optional permission broker for permission state.
            channel: The channel to send messages to.
        """
        self._message_bus = message_bus
        self._permission_broker = permission_broker
        self._channel = channel

        # Track accumulated content for final answer
        self._content_buffers: dict[str, list[str]] = {}
        self._pending_tools: dict[str, dict[str, Any]] = {}

        # Track active correlation from prompt_start for chunk buffering
        self._active_correlation_id: Optional[str] = None

        # Duplicate suppression: track emitted payload hashes per session
        self._emitted_hashes: dict[str, set[str]] = {}

    async def send_update(self, event: ACPUpdateEvent) -> None:
        """Handle an update event and render it.

        Args:
            event: The update event to render.
        """
        correlation_id = event.correlation_id
        session_id = event.payload.get("session_id", correlation_id)

        # Render based on event type
        if event.event_type == "prompt_start":
            await self._render_prompt_start(event, correlation_id, session_id)
        elif event.event_type == "prompt_end":
            await self._render_prompt_end(event, correlation_id, session_id)
        elif event.event_type == "tool_use_start":
            await self._render_tool_start(event, correlation_id, session_id)
        elif event.event_type == "tool_use_end":
            await self._render_tool_end(event, correlation_id, session_id)
        elif event.event_type == "tool_result":
            await self._render_tool_result(event, correlation_id, session_id)
        elif event.event_type == "permission_request":
            await self._render_permission_request(event, correlation_id, session_id)
        elif event.event_type == "permission_decision":
            await self._render_permission_decision(event, correlation_id, session_id)
        elif event.event_type == "initialize":
            await self._render_initialize(event, session_id)
        elif event.event_type == "new_session":
            await self._render_new_session(event, session_id)
        elif event.event_type == "cancel":
            await self._render_cancel(event, correlation_id, session_id)
        elif event.event_type == "shutdown":
            await self._render_shutdown(event, session_id)
        else:
            # Generic event rendering
            await self._render_generic(event, correlation_id, session_id)

    async def send_rendered(self, update: ACPRenderedUpdate) -> None:
        """Handle a pre-rendered update.

        Args:
            update: The rendered update to send.
        """
        # Convert to outbound message and send
        msg = OutboundMessage(
            channel=self._channel,
            chat_id="default",
            content=update.content,
            metadata=update.metadata,
        )
        await self._message_bus.publish_outbound(msg)

    async def stream_chunk(
        self, chunk: ACPStreamChunk, correlation_id: Optional[str] = None
    ) -> None:
        """Handle a stream chunk.

        Args:
            chunk: The stream chunk to process.
            correlation_id: Optional correlation ID for the chunk.
        """
        # Use provided correlation_id or fall back to active correlation
        key = correlation_id or self._active_correlation_id or "default"

        # Accumulate content chunks for later emission
        if chunk.type == ACPStreamChunkType.CONTENT_DELTA and chunk.content:
            if key not in self._content_buffers:
                self._content_buffers[key] = []
            self._content_buffers[key].append(chunk.content)

    async def _render_prompt_start(
        self, event: ACPUpdateEvent, correlation_id: Optional[str], session_id: Optional[str]
    ) -> None:
        """Render prompt start event."""
        content = event.payload.get("content", "")
        truncated = content[:50] + "..." if len(content) > 50 else content

        # Track active correlation for chunk buffering
        if correlation_id:
            self._active_correlation_id = correlation_id

        await self._publish(
            update_type="prompt_start",
            content=f"Processing: {truncated}",
            correlation_id=correlation_id,
            session_id=session_id,
        )

    async def _render_prompt_end(
        self, event: ACPUpdateEvent, correlation_id: Optional[str], session_id: Optional[str]
    ) -> None:
        """Render prompt end - emit final answer from accumulated content."""
        if correlation_id and correlation_id in self._content_buffers:
            # Join accumulated content for final answer
            final_content = "".join(self._content_buffers[correlation_id])
            if final_content:
                await self._publish(
                    update_type="final_answer",
                    content=final_content,
                    correlation_id=correlation_id,
                    session_id=session_id,
                )
            # Clear the buffer
            del self._content_buffers[correlation_id]
        else:
            await self._publish(
                update_type="prompt_end",
                content="Response complete",
                correlation_id=correlation_id,
                session_id=session_id,
            )

    async def _render_tool_start(
        self, event: ACPUpdateEvent, correlation_id: Optional[str], session_id: Optional[str]
    ) -> None:
        """Render tool start event."""
        tool_name = event.payload.get("tool_name", "unknown")
        tool_input = event.payload.get("tool_input", {})
        tool_use_id = event.payload.get("tool_use_id", "")

        # Track pending tool
        if correlation_id:
            self._pending_tools[correlation_id] = {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_use_id": tool_use_id,
            }

        content = f"Using tool: {tool_name}"
        if tool_input:
            # Add brief input context
            if "path" in tool_input:
                content += f" ({tool_input['path']})"
            elif "command" in tool_input:
                content += f" ({tool_input['command'][:30]})"

        await self._publish(
            update_type="tool_start",
            content=content,
            correlation_id=correlation_id,
            session_id=session_id,
        )

    async def _render_tool_end(
        self, event: ACPUpdateEvent, correlation_id: Optional[str], session_id: Optional[str]
    ) -> None:
        """Render tool end event."""
        tool_name = event.payload.get("tool_name", "unknown")

        await self._publish(
            update_type="tool_end",
            content=f"Tool complete: {tool_name}",
            correlation_id=correlation_id,
            session_id=session_id,
        )

        # Clear pending tool
        if correlation_id and correlation_id in self._pending_tools:
            del self._pending_tools[correlation_id]

    async def _render_tool_result(
        self, event: ACPUpdateEvent, correlation_id: Optional[str], session_id: Optional[str]
    ) -> None:
        """Render tool result event."""
        tool_name = event.payload.get("tool_name", "unknown")
        content = event.payload.get("content", "")

        # Truncate long results
        truncated = content[:200] + "..." if len(content) > 200 else content

        await self._publish(
            update_type="tool_result",
            content=f"{tool_name}: {truncated}",
            correlation_id=correlation_id,
            session_id=session_id,
        )

    async def _render_permission_request(
        self, event: ACPUpdateEvent, correlation_id: Optional[str], session_id: Optional[str]
    ) -> None:
        """Render permission request event."""
        perm_type = event.payload.get("permission_type", "unknown")
        description = event.payload.get("description", "")
        resource = event.payload.get("resource", "")

        content = f"Permission request ({perm_type})"
        if description:
            content += f": {description}"
        elif resource:
            content += f": {resource}"

        await self._publish(
            update_type="permission_request",
            content=content,
            correlation_id=correlation_id,
            session_id=session_id,
        )

    async def _render_permission_decision(
        self, event: ACPUpdateEvent, correlation_id: Optional[str], session_id: Optional[str]
    ) -> None:
        """Render permission decision event."""
        granted = event.payload.get("granted", False)
        reason = event.payload.get("reason", "")

        content = f"Permission {'approved' if granted else 'denied'}"
        if reason:
            content += f": {reason}"

        await self._publish(
            update_type="permission_decision",
            content=content,
            correlation_id=correlation_id,
            session_id=session_id,
        )

    async def _render_initialize(self, event: ACPUpdateEvent, session_id: Optional[str]) -> None:
        """Render initialize event."""
        await self._publish(
            update_type="initialize",
            content="Agent initialized",
            session_id=session_id,
        )

    async def _render_new_session(self, event: ACPUpdateEvent, session_id: Optional[str]) -> None:
        """Render new session event."""
        new_session_id = event.payload.get("session_id", "unknown")
        await self._publish(
            update_type="new_session",
            content=f"New session: {new_session_id[:8]}...",
            session_id=session_id,
        )

    async def _render_cancel(
        self, event: ACPUpdateEvent, correlation_id: Optional[str], session_id: Optional[str]
    ) -> None:
        """Render cancel event."""
        await self._publish(
            update_type="cancel",
            content="Operation cancelled",
            correlation_id=correlation_id,
            session_id=session_id,
        )

    async def _render_shutdown(self, event: ACPUpdateEvent, session_id: Optional[str]) -> None:
        """Render shutdown event."""
        await self._publish(
            update_type="shutdown",
            content="Agent shutting down",
            session_id=session_id,
        )

    async def _render_generic(
        self, event: ACPUpdateEvent, correlation_id: Optional[str], session_id: Optional[str]
    ) -> None:
        """Render generic event."""
        await self._publish(
            update_type=event.event_type,
            content=f"Event: {event.event_type}",
            correlation_id=correlation_id,
            session_id=session_id,
        )

    async def _publish(
        self,
        update_type: str,
        content: str,
        correlation_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Publish an outbound message with duplicate suppression.

        Args:
            update_type: The type of update.
            content: The content to render.
            correlation_id: Optional correlation ID.
            session_id: Optional session ID.
        """
        # Create the payload
        payload = RenderedPayload(
            update_type=update_type,
            content=content,
            correlation_id=correlation_id,
            session_id=session_id,
        )

        # Check for duplicates using deterministic hash
        key = session_id or correlation_id or "default"
        if key not in self._emitted_hashes:
            self._emitted_hashes[key] = set()

        # Generate hash of the payload
        hash_input = json.dumps(payload.to_hashable(), sort_keys=True)
        payload_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        # Suppress if we've already emitted this exact payload
        if payload_hash in self._emitted_hashes[key]:
            return

        # Track the hash
        self._emitted_hashes[key].add(payload_hash)

        # Publish the outbound message
        msg = OutboundMessage(
            channel=self._channel,
            chat_id=key,
            content=content,
            metadata={
                "update_type": update_type,
                "correlation_id": correlation_id,
            },
        )
        await self._message_bus.publish_outbound(msg)

    def clear_session(self, session_id: str) -> None:
        """Clear session state (for testing).

        Args:
            session_id: The session ID to clear.
        """
        self._emitted_hashes.pop(session_id, None)
        self._content_buffers.pop(session_id, None)
        self._pending_tools.pop(session_id, None)


class ACPRenderAdapter:
    """Adapter to make ACPRenderer usable as an ACPUpdateSink.

    This allows the renderer to be subscribed directly to an ACPUpdateAccumulator.
    """

    def __init__(self, renderer: ACPRenderer):
        """Initialize the adapter.

        Args:
            renderer: The renderer to adapt.
        """
        self._renderer = renderer

    async def send_update(self, event: ACPUpdateEvent) -> None:
        """Send an update event to the renderer."""
        await self._renderer.send_update(event)

    async def send_rendered(self, update: ACPRenderedUpdate) -> None:
        """Send a rendered update to the renderer."""
        await self._renderer.send_rendered(update)

    async def stream_chunk(self, chunk: ACPStreamChunk) -> None:
        """Stream a chunk to the renderer."""
        await self._renderer.stream_chunk(chunk)
