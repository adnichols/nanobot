"""SDK transport adapter for ACP.

This module provides a high-level client wrapper around the agent-client-protocol
SDK, handling connection lifecycle, notification routing, and error mapping.

The SDKClient wraps the SDK's Connection class and provides a clean API for
interacting with ACP-compliant agents (like OpenCode).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from acp import spawn_stdio_connection
from acp.connection import Connection
from acp.schema import (
    AgentNotification,
)

from nanobot.acp.interfaces import ACPCallbackRegistry, ACPSessionStore, ACPUpdateSink
from nanobot.acp.sdk_types import (
    from_sdk_initialize_response,
    from_sdk_notification,
    from_sdk_prompt_chunk,
    from_sdk_session_response,
    to_sdk_cancel_params,
    to_sdk_initialize_params,
    to_sdk_load_session_params,
    to_sdk_new_session_params,
    to_sdk_prompt_params,
)

logger = logging.getLogger(__name__)


class SDKError(Exception):
    """Base exception for SDK-related errors."""

    pass


class SDKConnectionError(SDKError):
    """Raised when connection to the agent fails."""

    pass


class SDKTimedOutError(SDKError):
    """Raised when an operation times out."""

    pass


class SDKInitializationError(SDKError):
    """Raised when agent initialization fails."""

    pass


class SDKSessionError(SDKError):
    """Raised when session operations fail."""

    pass


class SDKPromptError(SDKError):
    """Raised when prompt operations fail."""

    pass


class SDKNotificationHandler:
    """Handler for SDK notifications that routes to nanobot callbacks."""

    def __init__(
        self,
        update_sink: Optional[ACPUpdateSink] = None,
        callback_registry: Optional[ACPCallbackRegistry] = None,
        permission_broker: Any = None,
        filesystem_handler: Any = None,
        terminal_manager: Any = None,
    ):
        """Initialize the notification handler.

        Args:
            update_sink: Sink for update events.
            callback_registry: Registry for permission callbacks.
            permission_broker: Broker for permission requests.
            filesystem_handler: Handler for filesystem operations.
            terminal_manager: Manager for terminal operations.
        """
        self._update_sink = update_sink
        self._callback_registry = callback_registry
        self._permission_broker = permission_broker
        self._filesystem_handler = filesystem_handler
        self._terminal_manager = terminal_manager
        self._pending_responses: dict[str, asyncio.Future] = {}

    def __call__(self, notification: AgentNotification) -> None:
        """Handle an incoming notification from the agent.

        Args:
            notification: The notification from the agent.
        """
        method, params = from_sdk_notification(notification)
        logger.debug(f"Received notification: {method}")

        # Route based on method
        if method == "session/update":
            self._handle_session_update(params)
        elif method == "session/request_permission":
            asyncio.create_task(self._handle_permission_request(params))
        elif method == "fs/read_text_file":
            asyncio.create_task(self._handle_fs_read(params))
        elif method == "terminal/create":
            asyncio.create_task(self._handle_terminal_create(params))
        else:
            logger.debug(f"Unhandled notification method: {method}")

    def _handle_session_update(self, params: dict[str, Any]) -> None:
        """Handle session update notifications."""
        if self._update_sink is None:
            return

        update = params.get("update", {})
        # Send to update sink for rendering
        asyncio.create_task(self._update_sink.send_update(update))

    async def _handle_permission_request(self, params: dict[str, Any]) -> None:
        """Handle permission request notifications."""
        if self._permission_broker is None:
            logger.warning("Permission request received but no broker configured")
            return

        # Extract permission request details
        from nanobot.acp.types import ACPPermissionRequest

        request_id = params.get("request_id", "unknown")
        permission_type = params.get("permission_type", "unknown")
        description = params.get("description", "")
        resource = params.get("resource", "")

        request = ACPPermissionRequest(
            id=request_id,
            permission_type=permission_type,
            description=description,
            resource=resource,
        )

        decision = await self._permission_broker.request_permission(request)

        # Send response back to agent
        # This would be done via the connection's send_notification
        logger.debug(f"Permission decision: {decision.granted} - {decision.reason}")

    async def _handle_fs_read(self, params: dict[str, Any]) -> None:
        """Handle filesystem read request notifications."""
        if self._filesystem_handler is None:
            logger.warning("Filesystem read request but no handler configured")
            return

        from nanobot.acp.types import ACPFilesystemCallback

        callback = ACPFilesystemCallback(
            operation="read",
            path=params.get("path", ""),
            metadata=params,
        )

        decision = await self._filesystem_handler.handle_filesystem_callback(callback)
        logger.debug(f"Filesystem decision: {decision.granted} - {decision.reason}")

    async def _handle_terminal_create(self, params: dict[str, Any]) -> None:
        """Handle terminal create request notifications."""
        if self._terminal_manager is None:
            logger.warning("Terminal create request but no manager configured")
            return

        from nanobot.acp.types import ACPTerminalCallback

        callback = ACPTerminalCallback(
            command=params.get("command", ""),
            working_directory=params.get("working_directory"),
            environment=params.get("environment", {}),
            timeout=params.get("timeout"),
        )

        # Would need terminal permission handling
        logger.debug(f"Terminal create request: {callback.command}")


class SDKClient:
    """SDK-based ACP client.

    Provides a high-level API for interacting with ACP-compliant agents
    using the official agent-client-protocol SDK.
    """

    def __init__(
        self,
        agent_path: Optional[str] = None,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
        session_store: Optional[ACPSessionStore] = None,
        callback_registry: Optional[ACPCallbackRegistry] = None,
        update_sink: Optional[ACPUpdateSink] = None,
        permission_broker: Any = None,
        filesystem_handler: Any = None,
        terminal_manager: Any = None,
    ):
        """Initialize the SDK client.

        Args:
            agent_path: Path to the ACP agent executable (e.g., "opencode").
            args: Arguments to pass to the agent (e.g., ["acp"]).
            env: Environment variables for the agent process.
            cwd: Working directory for the agent process.
            session_store: Optional session store for persistence.
            callback_registry: Registry for permission callbacks.
            update_sink: Sink for update events.
            permission_broker: Broker for permission requests.
            filesystem_handler: Handler for filesystem operations.
            terminal_manager: Manager for terminal operations.
        """
        self.agent_path = agent_path
        self.args = args or []
        self.env = env
        self.cwd = cwd

        self._session_store = session_store
        self._callback_registry = callback_registry
        self._update_sink = update_sink
        self._permission_broker = permission_broker
        self._filesystem_handler = filesystem_handler
        self._terminal_manager = terminal_manager

        self._connection: Optional[Connection] = None
        self._process: Optional[Any] = None
        self._notification_handler: Optional[SDKNotificationHandler] = None
        self._current_session_id: Optional[str] = None
        self._capabilities: Optional[dict[str, Any]] = None
        self._initialized = False
        self._conn_context: Optional[Any] = None

    @property
    def is_initialized(self) -> bool:
        """Check if the client is initialized."""
        return self._initialized

    @property
    def current_session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return self._current_session_id

    @property
    def capabilities(self) -> Optional[dict[str, Any]]:
        """Get the agent capabilities."""
        return self._capabilities

    def set_notification_handler(self, handler: Callable[[str, dict[str, Any]], None]) -> None:
        """Set a custom notification handler.

        Args:
            handler: Function to call with (method, params) on notifications.
        """

        # Wrap the handler for SDK notifications
        def sdk_handler(notification: AgentNotification) -> None:
            method, params = from_sdk_notification(notification)
            handler(method, params)

        self._custom_notification_handler = sdk_handler

    async def initialize(self, session_id: Optional[str] = None) -> dict[str, Any]:
        """Initialize the client and agent.

        Args:
            session_id: Optional session ID to use.

        Returns:
            Dict containing initialization status and capabilities.

        Raises:
            SDKConnectionError: If connection to the agent fails.
            SDKInitializationError: If agent initialization fails.
        """
        if self._initialized:
            logger.warning("Client already initialized")
            return {
                "status": "already_initialized",
                "capabilities": self._capabilities,
            }

        if self.agent_path is None:
            # No agent path - just mark as initialized for testing
            self._initialized = True
            return {
                "status": "mock_initialized",
                "capabilities": {},
            }

        try:
            # Build the command
            command = [self.agent_path] + self.args

            # Create notification handler
            self._notification_handler = SDKNotificationHandler(
                update_sink=self._update_sink,
                callback_registry=self._callback_registry,
                permission_broker=self._permission_broker,
                filesystem_handler=self._filesystem_handler,
                terminal_manager=self._terminal_manager,
            )

            # Spawn the connection
            self._connection, self._process = await self._spawn_connection(
                command=command,
                handler=self._notification_handler,
            )

            # Send initialize request
            init_params = to_sdk_initialize_params(
                type(
                    "ACPInitializeRequest",
                    (),
                    {
                        "session_id": session_id or "default-session",
                        "system_prompt": "You are a helpful AI assistant.",
                    },
                )()
            )

            response = await self._connection.send_request(
                "initialize",
                init_params.model_dump(),
            )

            # Parse the response
            result = from_sdk_initialize_response(response)

            self._capabilities = result.get("capabilities", {})
            self._initialized = True

            return {
                "status": "initialized",
                "capabilities": self._capabilities,
            }

        except FileNotFoundError as e:
            raise SDKConnectionError(f"Agent not found: {self.agent_path}") from e
        except Exception as e:
            raise SDKInitializationError(f"Initialization failed: {e}") from e

    async def _spawn_connection(
        self,
        command: list[str],
        handler: Callable[[AgentNotification], None],
    ) -> tuple[Connection, Any]:
        """Spawn the stdio connection to the agent.

        Args:
            command: Command to spawn.
            handler: Notification handler.

        Returns:
            Tuple of (Connection, process).

        Raises:
            SDKConnectionError: If spawning fails.
        """
        try:
            # Get the async iterator from spawn_stdio_connection
            # Note: args must be passed as positional varargs, not keyword argument
            conn_iter = spawn_stdio_connection(
                handler=handler,
                command=command[0],
                *command[1:],
                env=self.env,
                cwd=self.cwd,
            )
            # Enter the context to get connection and process
            connection, process = await conn_iter.__aenter__()
            # Store the iterator for later cleanup
            self._conn_context = conn_iter
            return (connection, process)
        except Exception as e:
            raise SDKConnectionError(f"Failed to spawn agent: {e}") from e

    async def new_session(self) -> dict[str, Any]:
        """Create a new ACP session.

        Returns:
            Dict containing the new session ID.

        Raises:
            SDKConnectionError: If not connected.
            SDKSessionError: If session creation fails.
        """
        if not self._initialized:
            raise SDKConnectionError("Client not initialized. Call initialize() first.")

        # Test mode: create in-memory session when no agent_path
        if self._connection is None:
            session_id = f"mock-session-{asyncio.get_event_loop().time():.0f}"
            self._current_session_id = session_id
            return {
                "session_id": session_id,
                "status": "created",
            }

        try:
            session_id = f"session-{asyncio.get_event_loop().time():.0f}"
            params = to_sdk_new_session_params(session_id)

            response = await self._connection.send_request(
                "session/new",
                params.model_dump(),
            )

            result = from_sdk_session_response(response)
            self._current_session_id = result.get("session_id")

            return result

        except Exception as e:
            raise SDKSessionError(f"Failed to create session: {e}") from e

    async def load_session(self, session_id: str) -> dict[str, Any]:
        """Load an existing ACP session.

        Args:
            session_id: The session ID to load.

        Returns:
            Dict containing session status and data.

        Raises:
            SDKConnectionError: If not connected.
            SDKSessionError: If session loading fails.
        """
        if not self._initialized:
            raise SDKConnectionError("Client not initialized. Call initialize() first.")

        # Test mode: return mock session when no agent_path
        if self._connection is None:
            self._current_session_id = session_id
            return {
                "session_id": session_id,
                "status": "loaded",
                "session": {
                    "id": session_id,
                    "state": {},
                    "messages": [],
                },
            }

        try:
            params = to_sdk_load_session_params(session_id)

            response = await self._connection.send_request(
                "session/load",
                params.model_dump(),
            )

            result = from_sdk_session_response(response)
            self._current_session_id = session_id

            return result

        except Exception as e:
            raise SDKSessionError(f"Failed to load session: {e}") from e

    async def prompt(
        self,
        content: str,
        session_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Send a prompt to the ACP agent.

        Args:
            content: The prompt content.
            session_id: Optional session ID (uses current session if not provided).

        Returns:
            List of stream chunks from the agent.

        Raises:
            SDKConnectionError: If not connected.
            SDKPromptError: If prompt fails.
        """
        if not self._initialized:
            raise SDKConnectionError("Client not initialized. Call initialize() first.")

        target_session = session_id or self._current_session_id
        if not target_session:
            raise SDKPromptError(
                "No session ID available. Call new_session() or load_session() first."
            )

        # Test mode: return mock response when no agent_path
        if self._connection is None:
            return [
                {
                    "type": "message",
                    "content": f"Mock response to: {content}",
                }
            ]

        try:
            params = to_sdk_prompt_params(content, target_session)

            # Send the prompt request
            response = await self._connection.send_request(
                "prompt",
                params.model_dump(),
            )

            # Parse response into chunks
            chunks = []
            if response:
                chunk = from_sdk_prompt_chunk(response)
                chunks.append(chunk)

            return chunks

        except Exception as e:
            raise SDKPromptError(f"Prompt failed: {e}") from e

    async def cancel(self, session_id: Optional[str] = None) -> None:
        """Cancel an ongoing prompt operation.

        Args:
            session_id: Optional session ID (uses current session if not provided).

        Raises:
            SDKConnectionError: If not connected.
        """
        if not self._initialized or self._connection is None:
            # Not connected - nothing to cancel
            return

        target_session = session_id or self._current_session_id
        if not target_session:
            logger.warning("No session to cancel")
            return

        try:
            params = to_sdk_cancel_params(target_session)

            await self._connection.send_notification(
                "cancel",
                params.model_dump(),
            )

        except Exception as e:
            logger.warning(f"Cancel failed: {e}")

    async def close(self) -> None:
        """Close the client and cleanup resources."""
        # Exit the connection context if it exists
        if self._conn_context is not None:
            try:
                await self._conn_context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing connection context: {e}")
            self._conn_context = None

        self._connection = None
        self._process = None
        self._initialized = False
        self._current_session_id = None

    # Alias for compatibility with old ACPClient API
    async def shutdown(self) -> None:
        """Shutdown the client (alias for close())."""
        await self.close()

    def subscribe_updates(self, sink: ACPUpdateSink) -> None:
        """Subscribe to update events.

        Args:
            sink: The update sink to receive events.
        """
        self._update_sink = sink

    def register_filesystem_callback(self, handler: Any) -> None:
        """Register a filesystem permission handler.

        Args:
            handler: Async handler for filesystem callbacks.
        """
        # Store the handler for notification routing
        self._filesystem_handler = handler

    def register_terminal_callback(self, handler: Any) -> None:
        """Register a terminal permission handler.

        Args:
            handler: Async handler for terminal callbacks.
        """
        # Store the handler for notification routing
        self._terminal_manager = handler
