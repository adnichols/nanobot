"""ACP service interface.

This module provides a high-level service interface that integrates ACP
runtime with nanobot's session management, CLI, and chat functionality.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from nanobot.acp.interfaces import ACPCallbackRegistry, ACPSessionStore, ACPUpdateSink
from nanobot.acp.sdk_client import SDKClient, SDKError
from nanobot.acp.store import ACPSessionBindingStore
from nanobot.acp.types import ACPStreamChunk


@dataclass
class ACPServiceConfig:
    """Configuration for the ACP service."""

    agent_path: Optional[str] = None
    storage_dir: Optional[Path] = None
    workspace_dir: Optional[Path] = None
    callback_registry: Optional[ACPCallbackRegistry] = None
    agent_definition: Optional[Any] = None  # ACPAgentDefinition from config.schema
    permission_broker_factory: Optional[Callable[[str], Any]] = None


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
        self._clients: dict[str, SDKClient] = {}
        # Cache capabilities from initialize responses
        self._capabilities: dict[str, Any] = {}
        self._filesystem_handler: Any = None
        self._terminal_manager: Any = None

        # Initialize stores if storage dir is provided
        if self._config.storage_dir:
            from nanobot.acp.store import ACPFileSessionStore

            self._session_store = ACPFileSessionStore(self._config.storage_dir / "sessions")
            self._binding_store = ACPSessionBindingStore(self._config.storage_dir / "bindings")

    def _create_client(self, nanobot_session_key: str | None = None) -> SDKClient:
        """Create an SDK client with proper configuration.

        Returns:
            Configured SDKClient instance.
        """
        # Extract args, env, cwd from agent_definition if provided
        agent_def = self._config.agent_definition
        model = getattr(agent_def, "model", None) or None
        args = getattr(agent_def, "args", None) or []
        env = getattr(agent_def, "env", None) or None
        cwd = getattr(agent_def, "cwd", None) or None
        if cwd is None and self._config.workspace_dir is not None:
            cwd = str(self._config.workspace_dir)

        permission_broker = None
        if nanobot_session_key is not None and self._config.permission_broker_factory is not None:
            permission_broker = self._config.permission_broker_factory(nanobot_session_key)

        return SDKClient(
            agent_path=self._config.agent_path,
            model=model,
            args=args if args else None,
            env=env,
            cwd=cwd,
            session_store=self._session_store,
            callback_registry=self._config.callback_registry,
            permission_broker=permission_broker,
            filesystem_handler=self._filesystem_handler,
            terminal_manager=self._terminal_manager,
        )

    async def _apply_session_overrides(self, client: SDKClient, session_id: str) -> None:
        """Apply configured ACP session overrides after create/load."""
        if client.model:
            await client.set_model(client.model, session_id=session_id)

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
        # Create a new client for this session with full agent definition
        client = self._create_client(nanobot_session_key)

        # Initialize and create session
        await client.initialize()
        result = await client.new_session()

        acp_session_id = result.get("session_id")
        if not isinstance(acp_session_id, str) or not acp_session_id:
            raise RuntimeError("ACP session creation did not return a session_id")

        await self._apply_session_overrides(client, acp_session_id)

        # Cache capabilities for this agent
        if client.capabilities:
            self._capabilities[agent_id] = client.capabilities

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
        active_client = self._clients.get(nanobot_session_key)
        if active_client is not None and active_client.current_session_id:
            binding = None
            if self._binding_store:
                binding = self._binding_store.load_binding(nanobot_session_key)

            agent_id = (
                binding.acp_agent_id
                if binding is not None
                else getattr(self._config.agent_definition, "id", None) or "default"
            )
            return {
                "nanobot_session_key": nanobot_session_key,
                "acp_session_id": active_client.current_session_id,
                "agent_id": agent_id,
                "status": "loaded",
                "session": None,
            }

        # Check for existing binding
        binding = None
        if self._binding_store:
            binding = self._binding_store.load_binding(nanobot_session_key)

        if not binding:
            # No existing session - create a new one
            return await self.create_session(nanobot_session_key)

        # Create client and initialize
        client = self._create_client(nanobot_session_key)
        await client.initialize()

        # Cache capabilities
        if client.capabilities:
            self._capabilities[binding.acp_agent_id] = client.capabilities

        # Check if agent has loadSession capability
        agent_capabilities = client.capabilities or {}
        has_load_session = agent_capabilities.get("loadSession", False)

        acp_session_id: str
        status: str

        if has_load_session:
            # Agent supports session/load - try to load existing session
            try:
                result = await client.load_session(binding.acp_session_id)
                acp_session_id = binding.acp_session_id
                status = "loaded"
                await self._apply_session_overrides(client, acp_session_id)
            except SDKError:
                # Load failed - fallback to creating new session
                result = await client.new_session()
                acp_session_id = result.get("session_id", "")
                status = "created"
                await self._apply_session_overrides(client, acp_session_id)
                # Rebind the new session
                if self._binding_store:
                    from nanobot.acp.store import ACPSessionBinding

                    new_binding = ACPSessionBinding(
                        nanobot_session_key=nanobot_session_key,
                        acp_agent_id=binding.acp_agent_id,
                        acp_session_id=acp_session_id,
                    )
                    self._binding_store.save_binding(new_binding)
        else:
            # Agent doesn't support loadSession - create new session and rebind
            result = await client.new_session()
            acp_session_id = result.get("session_id", "")
            status = "created"
            await self._apply_session_overrides(client, acp_session_id)
            # Rebind the new session
            if self._binding_store:
                from nanobot.acp.store import ACPSessionBinding

                new_binding = ACPSessionBinding(
                    nanobot_session_key=nanobot_session_key,
                    acp_agent_id=binding.acp_agent_id,
                    acp_session_id=acp_session_id,
                )
                self._binding_store.save_binding(new_binding)

        # Track the client
        self._clients[nanobot_session_key] = client

        return {
            "nanobot_session_key": nanobot_session_key,
            "acp_session_id": acp_session_id,
            "agent_id": binding.acp_agent_id,
            "status": status,
            "session": result.get("session"),
        }

    async def process_message(
        self,
        nanobot_session_key: str,
        message: str,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> list[ACPStreamChunk]:
        """Process an incoming chat message through ACP.

        Args:
            nanobot_session_key: The nanobot session key.
            message: The message content.
            on_chunk: Optional callback invoked for each live text chunk.

        Returns:
            List of response stream chunks.
        """
        # Ensure we have a session
        if nanobot_session_key not in self._clients:
            await self.load_session(nanobot_session_key)

        client = self._clients[nanobot_session_key]
        return await client.prompt(message, on_chunk=on_chunk)

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

    def clear_update_subscription(self, nanobot_session_key: str) -> None:
        """Clear the active update sink for a session, if one exists."""
        if nanobot_session_key in self._clients:
            self._clients[nanobot_session_key].clear_update_subscription()

    def register_filesystem_callback(self, handler: Any) -> None:
        """Register a filesystem permission handler for all sessions.

        Args:
            handler: Async handler for filesystem callbacks.
        """
        register_callback = True
        if hasattr(handler, "handle_filesystem_callback"):
            self._filesystem_handler = handler
            register_callback = False
        elif self._filesystem_handler is None:
            self._filesystem_handler = handler

        if register_callback and self._config.callback_registry is not None:
            self._config.callback_registry.register_filesystem_callback(handler)

        client_handler = (
            self._filesystem_handler if self._filesystem_handler is not None else handler
        )
        for client in self._clients.values():
            client.register_filesystem_callback(client_handler)

    def register_terminal_callback(self, handler: Any) -> None:
        """Register a terminal permission handler for all sessions.

        Args:
            handler: Async handler for terminal callbacks.
        """
        register_callback = True
        if hasattr(handler, "create"):
            self._terminal_manager = handler
            register_callback = False
        elif self._terminal_manager is None:
            self._terminal_manager = handler

        if register_callback and self._config.callback_registry is not None:
            self._config.callback_registry.register_terminal_callback(handler)

        client_handler = self._terminal_manager if self._terminal_manager is not None else handler
        for client in self._clients.values():
            client.register_terminal_callback(client_handler)

    async def shutdown_session(self, nanobot_session_key: str) -> None:
        """Shutdown a specific session.

        Args:
            nanobot_session_key: The nanobot session key.
        """
        if nanobot_session_key in self._clients:
            await self._clients[nanobot_session_key].shutdown()
            del self._clients[nanobot_session_key]

    async def reset_session(self, nanobot_session_key: str) -> None:
        """Drop both live client state and any persisted ACP binding."""
        shutdown_error: Exception | None = None
        try:
            await self.shutdown_session(nanobot_session_key)
        except Exception as exc:  # pragma: no cover - defensive transport cleanup path
            shutdown_error = exc

        if self._binding_store is not None:
            self._binding_store.delete_binding(nanobot_session_key)

        if shutdown_error is not None:
            raise shutdown_error

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
