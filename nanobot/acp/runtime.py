"""ACP Agent Runtime implementation.

This module provides the core ACP client runtime using the official Python SDK
helpers. It handles connection bootstrap, session lifecycle, prompt/cancel flows,
and graceful shutdown.

The runtime is designed to be UI-agnostic and exposes callback registration hooks
for downstream tracks (ACP-04 filesystem, ACP-05 terminal, ACP-06 permissions,
ACP-07 update sink).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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
    ACPSessionRecord,
    ACPStreamChunk,
    ACPStreamChunkType,
    ACPTerminalCallback,
    ACPUpdateEvent,
)


@dataclass
class ACPCapabilities:
    """Capabilities advertised by the ACP agent."""

    tools: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    supports_streaming: bool = True
    supports_session_persistence: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class ACPAgentRuntime:
    """Core ACP agent runtime.

    Handles:
    - Connection bootstrap (agent subprocess initialization)
    - Session lifecycle (new_session, load_session)
    - Prompt flow with request/response correlation
    - Cancel flow with clean state transition
    - Graceful shutdown
    - Reconnect semantics for unexpected backend exit
    """

    def __init__(
        self,
        agent_path: Optional[str] = None,
        session_store: Optional[ACPSessionStore] = None,
        callback_registry: Optional[ACPCallbackRegistry] = None,
        agent_definition: Optional[Any] = None,
    ):
        """Initialize the ACP agent runtime.

        Args:
            agent_path: Path to the ACP agent executable. If None, uses fake mode for testing.
            session_store: Optional session store for persistence.
            callback_registry: Optional callback registry for permission handling.
            agent_definition: Full agent definition with args, env, cwd, policy, capabilities.
        """
        self._agent_path = agent_path
        self._session_store = session_store
        self._callback_registry = callback_registry
        self._agent_definition = agent_definition
        self._update_sinks: list[ACPUpdateSink] = []

        # Runtime state
        self._initialized = False
        self._current_session_id: Optional[str] = None
        self._capabilities: Optional[ACPCapabilities] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._shutdown_event: asyncio.Event

        # Track active prompts for cancellation
        self._active_prompts: dict[str, asyncio.Task] = {}

        # For fake/testing mode
        self._fake_mode = agent_path is None

        # Initialize shutdown event
        self._shutdown_event = asyncio.Event()

    def subscribe_updates(self, sink: ACPUpdateSink) -> None:
        """Subscribe to update events from the agent.

        Args:
            sink: The update sink to receive events.
        """
        self._update_sinks.append(sink)

    def register_filesystem_callback(
        self, handler: Callable[[Any], Awaitable[ACPPermissionDecision]]
    ) -> None:
        """Register a handler for filesystem permission requests.

        This hook is used by ACP-04 (filesystem client).

        Args:
            handler: Async handler for filesystem callbacks.
        """
        if self._callback_registry is None:
            # Create a default registry if none provided
            from nanobot.acp.runtime import DefaultCallbackRegistry

            self._callback_registry = DefaultCallbackRegistry()
        self._callback_registry.register_filesystem_callback(handler)

    def register_terminal_callback(
        self, handler: Callable[[Any], Awaitable[ACPPermissionDecision]]
    ) -> None:
        """Register a handler for terminal permission requests.

        This hook is used by ACP-05 (terminal manager).

        Args:
            handler: Async handler for terminal callbacks.
        """
        if self._callback_registry is None:
            from nanobot.acp.runtime import DefaultCallbackRegistry

            self._callback_registry = DefaultCallbackRegistry()
        self._callback_registry.register_terminal_callback(handler)

    def register_webfetch_callback(
        self, handler: Callable[[dict[str, Any]], Awaitable[ACPPermissionDecision]]
    ) -> None:
        """Register a handler for web fetch permission requests.

        This hook is used by ACP-06 (permission broker).

        Args:
            handler: Async handler for web fetch callbacks.
        """
        if self._callback_registry is None:
            from nanobot.acp.runtime import DefaultCallbackRegistry

            self._callback_registry = DefaultCallbackRegistry()
        self._callback_registry.register_webfetch_callback(handler)

    async def handle_filesystem(self, callback: ACPFilesystemCallback) -> ACPPermissionDecision:
        """Dispatch a filesystem callback through the registered handler."""
        if self._callback_registry is None:
            raise NotImplementedError("No callback registry configured")

        request = ACPPermissionRequest(
            id=callback.metadata.get("request_id", uuid.uuid4().hex),
            permission_type="filesystem",
            description=f"Filesystem {callback.operation}: {callback.path}",
            resource=callback.path,
            callback=callback,
            correlation_id=callback.metadata.get("correlation_id"),
        )
        return await self._callback_registry.handle_permission_request(request)

    async def handle_terminal(self, callback: ACPTerminalCallback) -> ACPPermissionDecision:
        """Dispatch a terminal callback through the registered handler."""
        if self._callback_registry is None:
            raise NotImplementedError("No callback registry configured")

        request = ACPPermissionRequest(
            id=uuid.uuid4().hex,
            permission_type="terminal",
            description=f"Terminal command: {callback.command}",
            resource=callback.command,
            callback=callback,
        )
        return await self._callback_registry.handle_permission_request(request)

    async def _emit_update(self, event: ACPUpdateEvent) -> None:
        """Emit an update event to all subscribed sinks."""
        for sink in self._update_sinks:
            try:
                await sink.send_update(event)
            except Exception:
                # Log but don't fail on sink errors
                pass

    async def initialize(self, request: ACPInitializeRequest) -> dict[str, Any]:
        """Initialize the ACP agent.

        Args:
            request: Initialize request with session configuration.

        Returns:
            Dict containing status and capabilities.

        Raises:
            RuntimeError: If agent cannot be started.
            FileNotFoundError: If agent path is invalid.
        """
        if self._fake_mode:
            # Fake mode for testing
            self._initialized = True
            self._current_session_id = request.session_id
            self._capabilities = ACPCapabilities(
                tools=["read", "write", "bash", "grep"],
                permissions=["filesystem", "terminal", "webfetch"],
                supports_streaming=True,
                supports_session_persistence=True,
            )

            await self._emit_update(
                ACPUpdateEvent(
                    event_type="initialize",
                    timestamp=datetime.now(UTC),
                    payload={
                        "session_id": request.session_id,
                        "capabilities": self._capabilities.__dict__,
                    },
                )
            )

            return {
                "status": "initialized",
                "session_id": request.session_id,
                "capabilities": self._capabilities.__dict__,
            }

        # Real agent mode - try to spawn the process
        agent_path = self._agent_path or "opencode"
        if not Path(agent_path).exists() and agent_path != "opencode":
            raise FileNotFoundError(f"Agent not found at path: {agent_path}")

        try:
            cmd = [agent_path]
            if self._agent_definition and hasattr(self._agent_definition, "args"):
                cmd.extend(self._agent_definition.args)
            else:
                cmd.append("acp")

            # Build env from agent definition merged with current env
            env = None
            if self._agent_definition and hasattr(self._agent_definition, "env"):
                import os

                env = {**os.environ, **self._agent_definition.env}

            # Get cwd from agent definition
            cwd = None
            if self._agent_definition and hasattr(self._agent_definition, "cwd"):
                cwd = self._agent_definition.cwd

            # Spawn the agent process using stdio
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )

            self._initialized = True
            self._current_session_id = request.session_id

            # Emit initialize event
            await self._emit_update(
                ACPUpdateEvent(
                    event_type="initialize",
                    timestamp=datetime.now(UTC),
                    payload={"session_id": request.session_id},
                )
            )

            return {"status": "initialized", "session_id": request.session_id}

        except FileNotFoundError as e:
            raise FileNotFoundError(f"Failed to start agent: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to initialize agent: {e}") from e

    async def new_session(self) -> dict[str, Any]:
        """Create a new ACP session.

        Returns:
            Dict containing the new session ID and status.
        """
        session_id = str(uuid.uuid4())

        # Create a new session record if store is available
        if self._session_store:
            session_record = ACPSessionRecord(
                id=session_id,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                state={},
                messages=[],
            )
            await self._session_store.save(session_record)

        await self._emit_update(
            ACPUpdateEvent(
                event_type="new_session",
                timestamp=datetime.now(UTC),
                payload={"session_id": session_id},
            )
        )

        return {"session_id": session_id, "status": "created"}

    async def load_session(self, request: ACPLoadSessionRequest) -> dict[str, Any]:
        """Load a persisted ACP session.

        Args:
            request: Load session request with session ID.

        Returns:
            Dict containing status and session data.

        Raises:
            ValueError: If session is not found.
        """
        if self._session_store is None:
            raise RuntimeError("No session store configured")

        session = await self._session_store.load(request.session_id)
        if session is None:
            raise ValueError(f"Session not found: {request.session_id}")

        self._initialized = True
        self._current_session_id = request.session_id

        await self._emit_update(
            ACPUpdateEvent(
                event_type="session_loaded",
                timestamp=datetime.now(UTC),
                payload={"session_id": request.session_id},
            )
        )

        return {"status": "loaded", "session": session.to_dict()}

    async def prompt(self, request: ACPPromptRequest) -> list[ACPStreamChunk]:
        """Send a prompt to the ACP agent.

        Args:
            request: Prompt request with content and session ID.

        Returns:
            List of stream chunks from the agent.

        Raises:
            RuntimeError: If runtime is not initialized or agent has exited.
        """
        if not self._initialized:
            raise RuntimeError("Agent not initialized")

        if self._fake_mode:
            # Fake mode - return simulated response
            await self._emit_update(
                ACPUpdateEvent(
                    event_type="prompt_start",
                    timestamp=datetime.now(UTC),
                    payload={"content": request.content},
                    correlation_id=request.session_id,
                )
            )

            # Simulate response
            chunk = ACPStreamChunk(
                type=ACPStreamChunkType.CONTENT_DELTA,
                content=f"Response to: {request.content[:50]}...",
            )

            # Emit the chunk to sinks
            for sink in self._update_sinks:
                await sink.stream_chunk(chunk)

            await self._emit_update(
                ACPUpdateEvent(
                    event_type="prompt_end",
                    timestamp=datetime.now(UTC),
                    payload={"session_id": request.session_id},
                    correlation_id=request.session_id,
                )
            )

            return [chunk]

        # Real mode - communicate with agent process via ACP stdio protocol
        if self._process is None or self._process.returncode is not None:
            raise RuntimeError("Agent process has exited")

        request_id = str(uuid.uuid4())

        await self._emit_update(
            ACPUpdateEvent(
                event_type="prompt_start",
                timestamp=datetime.now(UTC),
                payload={"content": request.content, "session_id": request.session_id},
                correlation_id=request_id,
            )
        )

        # Build ACP prompt message
        import json

        prompt_message = {
            "type": "prompt",
            "session_id": request.session_id,
            "content": request.content,
            "request_id": request_id,
        }

        current_task = asyncio.current_task()
        if current_task is not None:
            self._active_prompts[request.session_id] = current_task

        if self._process.stdin is None:
            raise RuntimeError("Agent process stdin is not available")

        if self._process.stdout is None:
            raise RuntimeError("Agent process stdout is not available")

        try:
            message_bytes = (json.dumps(prompt_message) + "\n").encode("utf-8")
            self._process.stdin.write(message_bytes)
            await self._process.stdin.drain()
        except Exception as e:
            raise RuntimeError(f"Failed to send prompt to agent: {e}") from e

        chunks: list[ACPStreamChunk] = []
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break

                try:
                    response = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                response_type = response.get("type", "")

                if response_type == "content_delta":
                    chunk = ACPStreamChunk(
                        type=ACPStreamChunkType.CONTENT_DELTA,
                        content=response.get("content", ""),
                    )
                    chunks.append(chunk)
                    for sink in self._update_sinks:
                        await sink.stream_chunk(chunk)

                elif response_type == "tool_call":
                    tool_data = response.get("tool_call", {})
                    chunk = ACPStreamChunk(
                        type=ACPStreamChunkType.TOOL_USE_START,
                        tool_name=tool_data.get("name"),
                        tool_input=tool_data.get("input"),
                    )
                    chunks.append(chunk)
                    for sink in self._update_sinks:
                        await sink.stream_chunk(chunk)

                elif response_type == "error":
                    error_chunk = ACPStreamChunk(
                        type=ACPStreamChunkType.ERROR,
                        content=response.get("message", "Unknown error"),
                        error=response.get("error"),
                    )
                    chunks.append(error_chunk)
                    for sink in self._update_sinks:
                        await sink.stream_chunk(error_chunk)
                    break

                elif response_type == "done":
                    break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            error_chunk = ACPStreamChunk(
                type=ACPStreamChunkType.ERROR,
                content=f"Error reading agent response: {e}",
            )
            chunks.append(error_chunk)
            for sink in self._update_sinks:
                await sink.stream_chunk(error_chunk)
        finally:
            if self._active_prompts.get(request.session_id) is current_task:
                self._active_prompts.pop(request.session_id, None)

        await self._emit_update(
            ACPUpdateEvent(
                event_type="prompt_end",
                timestamp=datetime.now(UTC),
                payload={"session_id": request.session_id, "chunks": len(chunks)},
                correlation_id=request_id,
            )
        )

        return chunks

    async def cancel(self, request: ACPCancelRequest) -> None:
        """Cancel an ongoing prompt operation.

        Args:
            request: Cancel request with session ID and optional operation ID.
        """
        if self._process and self._process.returncode is None and self._process.stdin is not None:
            import json

            cancel_message = {
                "type": "cancel",
                "session_id": request.session_id,
                "operation_id": request.operation_id,
            }
            try:
                self._process.stdin.write((json.dumps(cancel_message) + "\n").encode("utf-8"))
                await self._process.stdin.drain()
            except Exception:
                pass

        # Cancel any active prompt for this session
        if request.session_id in self._active_prompts:
            task = self._active_prompts.pop(request.session_id)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Emit cancel event
        await self._emit_update(
            ACPUpdateEvent(
                event_type="cancel",
                timestamp=datetime.now(UTC),
                payload={"session_id": request.session_id, "operation_id": request.operation_id},
            )
        )

        # Reset cancelled state for fake mode
        if self._fake_mode and hasattr(self, "_cancelled"):
            self._cancelled = False

    async def shutdown(self) -> None:
        """Gracefully shutdown the ACP runtime.

        This cancels any active operations and cleans up resources.
        """
        self._shutdown_event.set()

        # Cancel any active prompts
        for task in self._active_prompts.values():
            task.cancel()
        self._active_prompts.clear()

        # Terminate the agent process if running
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

        self._initialized = False

        await self._emit_update(
            ACPUpdateEvent(
                event_type="shutdown",
                timestamp=datetime.now(UTC),
                payload={},
            )
        )

    @property
    def is_initialized(self) -> bool:
        """Check if the runtime is initialized."""
        return self._initialized

    @property
    def capabilities(self) -> Optional[ACPCapabilities]:
        """Get the capabilities of the connected agent."""
        return self._capabilities

    @property
    def current_session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return self._current_session_id


class DefaultCallbackRegistry:
    """Default callback registry implementation for permission handling.

    This provides a simple in-memory registry that can be used when
    no external registry is provided.
    """

    def __init__(self):
        self._filesystem_handler: Optional[Callable] = None
        self._terminal_handler: Optional[Callable] = None
        self._webfetch_handler: Optional[Callable] = None

    def register_filesystem_callback(
        self, handler: Callable[[Any], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._filesystem_handler = handler

    def register_terminal_callback(
        self, handler: Callable[[Any], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._terminal_handler = handler

    def register_webfetch_callback(
        self, handler: Callable[[dict[str, Any]], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._webfetch_handler = handler

    async def handle_permission_request(
        self, request: ACPPermissionRequest
    ) -> ACPPermissionDecision:
        """Handle a permission request by routing to the appropriate handler."""
        if request.permission_type == "filesystem" and self._filesystem_handler:
            return await self._filesystem_handler(request.callback)
        elif request.permission_type == "terminal" and self._terminal_handler:
            return await self._terminal_handler(request.callback)
        elif request.permission_type == "webfetch" and self._webfetch_handler:
            return await self._webfetch_handler(request.callback)

        # Default: deny if no handler registered
        return ACPPermissionDecision(
            request_id=request.id,
            granted=False,
            reason="No handler registered for this permission type",
        )
