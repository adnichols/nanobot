"""ACP permission broker.

This module handles permission requests from ACP agents in both:
- Interactive mode: user approval/denial via callback handlers
- Unattended mode: policy-driven resolution without user interaction

The broker:
- Supports allow, deny, timeout behaviors
- Handles interactive permission requests (user approval)
- Handles unattended automation mode (policy-driven)
- Maintains correlation state across overlapping requests
- Prevents indefinite blocking in non-interactive mode
- Integrates with permission callback registration from ACP-03

This is UI-agnostic - channel-specific prompts and rendering belong to
later integration tracks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, cast

from nanobot.acp.interfaces import ACPCallbackRegistry
from nanobot.acp.policy import PermissionMode, UnattendedPermissionPolicy
from nanobot.acp.types import (
    ACPFilesystemCallback,
    ACPPermissionDecision,
    ACPPermissionRequest,
    ACPTerminalCallback,
)

RUNTIME_PERMISSION_POLICIES = {"allow", "deny", "ask", "auto"}


@dataclass
class PermissionRequestState:
    """State tracking for an in-flight permission request."""

    request: ACPPermissionRequest
    future: asyncio.Future[ACPPermissionDecision]
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ACPPermissionBroker:
    """Permission broker for handling ACP permission requests.

    This broker handles permission requests in two modes:
    - Interactive (interactive=True): Uses callback handlers for user approval
    - Unattended (interactive=False): Uses policy for automatic resolution

    Attributes:
        callback_registry: Registry for permission callback handlers.
        interactive: Whether running in interactive mode (user can approve/deny).
        policy: Policy for unattended permission resolution.
        timeout: Timeout in seconds for permission requests in interactive mode.
    """

    def __init__(
        self,
        callback_registry: Optional[ACPCallbackRegistry] = None,
        interactive: bool = True,
        policy: Optional[UnattendedPermissionPolicy] = None,
        timeout: Optional[float] = 30.0,
    ):
        """Initialize the permission broker.

        Args:
            callback_registry: Registry for permission callback handlers.
            interactive: Whether running in interactive mode.
            policy: Policy for unattended permission resolution.
            timeout: Timeout in seconds for permission requests.
        """
        self._callback_registry = callback_registry
        self._interactive = interactive
        self._policy = policy
        self._timeout = timeout

        # Track in-flight requests for correlation
        self._pending_requests: dict[str, PermissionRequestState] = {}

    @property
    def is_interactive(self) -> bool:
        """Check if running in interactive mode."""
        return self._interactive

    @property
    def policy(self) -> UnattendedPermissionPolicy:
        """Get the current permission policy."""
        if self._policy is not None:
            return self._policy
        if self._interactive:
            return UnattendedPermissionPolicy(default_mode="ask")
        return UnattendedPermissionPolicy(default_mode="deny")

    def set_policy(self, policy: UnattendedPermissionPolicy) -> None:
        """Set a new permission policy.

        Args:
            policy: The new policy to use.
        """
        self._policy = policy

    async def request_permission(self, request: ACPPermissionRequest) -> ACPPermissionDecision:
        """Request permission for an ACP operation.

        This method handles the permission request based on the current mode:
        - Interactive: Uses callback handlers, respects timeout
        - Unattended: Uses policy for automatic resolution

        Args:
            request: The permission request to process.

        Returns:
            The permission decision (allow or deny).
        """
        # Store request for correlation tracking
        self._pending_requests[request.id] = PermissionRequestState(
            request=request,
            future=asyncio.get_event_loop().create_future(),
        )

        try:
            if self._interactive:
                return await self._handle_interactive_request(request)
            else:
                return await self._handle_unattended_request(request)
        finally:
            # Clean up tracking
            self._pending_requests.pop(request.id, None)

    async def _handle_interactive_request(
        self, request: ACPPermissionRequest
    ) -> ACPPermissionDecision:
        """Handle a permission request in interactive mode.

        Uses callback handlers with timeout support.

        Args:
            request: The permission request.

        Returns:
            The permission decision.
        """
        mode = self._resolve_mode(request)
        action = self._get_action_key(request)

        if mode == "allow":
            return self._create_approval(
                request,
                f"Allowed by trusted interactive policy (action: {action})",
            )

        if mode == "deny":
            return self._create_denial(
                request,
                f"Denied by trusted interactive policy (action: {action})",
            )

        if self._callback_registry is None:
            return self._create_denial(
                request, "No callback registry configured for interactive mode"
            )

        try:
            # Use asyncio.wait_for to implement timeout
            decision = await asyncio.wait_for(
                self._callback_registry.handle_permission_request(request),
                timeout=self._timeout,
            )
            return decision
        except asyncio.TimeoutError:
            return self._create_denial(
                request, f"Permission request timed out after {self._timeout}s"
            )
        except Exception as e:
            return self._create_denial(request, f"Permission request failed: {e}")

    async def _handle_unattended_request(
        self, request: ACPPermissionRequest
    ) -> ACPPermissionDecision:
        """Handle a permission request in unattended mode.

        Uses policy for automatic resolution without blocking.

        Args:
            request: The permission request.

        Returns:
            The permission decision based on policy.
        """
        action = self._get_action_key(request)
        mode = self._resolve_mode(request)

        if mode == "allow":
            return self._create_approval(request, f"Allowed by policy (action: {action})")
        elif mode == "deny":
            return self._create_denial(request, f"Denied by policy (action: {action})")
        else:  # mode == "ask"
            # In unattended mode, "ask" means try callback with short timeout,
            # then fall back to deny
            return await self._handle_unattended_ask(request, action)

    async def _handle_unattended_ask(
        self, request: ACPPermissionRequest, action: str
    ) -> ACPPermissionDecision:
        """Handle "ask" mode in unattended scenario.

        Tries callback handler with a short timeout, then falls back to deny.

        Args:
            request: The permission request.
            action: The action key.

        Returns:
            The permission decision.
        """
        if self._callback_registry is None:
            return self._create_denial(
                request, f"No handler available for ask mode (action: {action})"
            )

        # Use a shorter timeout for unattended "ask" mode
        ask_timeout = min(self._timeout or 30.0, 5.0)

        try:
            decision = await asyncio.wait_for(
                self._callback_registry.handle_permission_request(request),
                timeout=ask_timeout,
            )
            return decision
        except asyncio.TimeoutError:
            return self._create_denial(
                request,
                f"Ask mode timeout in unattended (action: {action}, timeout: {ask_timeout}s)",
            )
        except Exception:
            # Fall back to deny on any error in unattended mode
            return self._create_denial(request, f"Ask mode failed in unattended (action: {action})")

    def _get_action_key(self, request: ACPPermissionRequest) -> str:
        """Get the action key for policy resolution.

        Constructs a key from permission_type and resource/description.

        Args:
            request: The permission request.

        Returns:
            An action key string for policy resolution.
        """
        # Use permission type as base
        permission_type = request.permission_type

        # Try to extract more specific action from resource or description
        # For filesystem: could be read/write/delete based on resource or description
        # For terminal: could be command name from description

        # Simple heuristic: combine type with some context
        if request.resource:
            # Extract last path component as potential action
            parts = request.resource.rstrip("/").split("/")
            if parts:
                return f"{permission_type}:{parts[-1]}"

        return permission_type

    def _resolve_mode(self, request: ACPPermissionRequest) -> PermissionMode:
        """Resolve the effective permission mode for the current request."""
        action = self._get_action_key(request)
        return self.policy.resolve(action)

    def _create_approval(
        self, request: ACPPermissionRequest, reason: Optional[str] = None
    ) -> ACPPermissionDecision:
        """Create an approval decision.

        Args:
            request: The original request.
            reason: Optional reason for the approval.

        Returns:
            An approval decision.
        """
        return ACPPermissionDecision(
            request_id=request.id,
            granted=True,
            reason=reason or "Approved",
            timestamp=datetime.now(timezone.utc),
        )

    def _create_denial(
        self, request: ACPPermissionRequest, reason: Optional[str] = None
    ) -> ACPPermissionDecision:
        """Create a denial decision.

        Args:
            request: The original request.
            reason: Optional reason for the denial.

        Returns:
            A denial decision.
        """
        return ACPPermissionDecision(
            request_id=request.id,
            granted=False,
            reason=reason or "Denied",
            timestamp=datetime.now(timezone.utc),
        )

    def get_pending_request(self, request_id: str) -> Optional[PermissionRequestState]:
        """Get the state of a pending permission request.

        Useful for correlation and debugging.

        Args:
            request_id: The request ID to look up.

        Returns:
            The request state if found, None otherwise.
        """
        return self._pending_requests.get(request_id)

    @property
    def pending_count(self) -> int:
        """Get the count of pending permission requests.

        Useful for monitoring and debugging.

        Returns:
            Number of in-flight permission requests.
        """
        return len(self._pending_requests)


class ACPCallbackRouter:
    """Concrete callback registry for ACP permission routing.

    This keeps the live service path on the same callback contract used by the
    tests so interactive `ask` policy sessions can route permission requests
    through registered handlers once those handlers are wired.
    """

    def __init__(self):
        self._filesystem_handler: Optional[
            Callable[[ACPFilesystemCallback], Awaitable[ACPPermissionDecision]]
        ] = None
        self._terminal_handler: Optional[
            Callable[[ACPTerminalCallback], Awaitable[ACPPermissionDecision]]
        ] = None
        self._webfetch_handler: Optional[
            Callable[[dict[str, object]], Awaitable[ACPPermissionDecision]]
        ] = None

    def register_filesystem_callback(
        self, handler: Callable[[ACPFilesystemCallback], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._filesystem_handler = handler

    def register_terminal_callback(
        self, handler: Callable[[ACPTerminalCallback], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._terminal_handler = handler

    def register_webfetch_callback(
        self, handler: Callable[[dict[str, object]], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._webfetch_handler = handler

    async def handle_permission_request(
        self, request: ACPPermissionRequest
    ) -> ACPPermissionDecision:
        if request.permission_type == "filesystem" and self._filesystem_handler is not None:
            return await self._filesystem_handler(request.callback)

        if request.permission_type == "terminal" and self._terminal_handler is not None:
            return await self._terminal_handler(request.callback)

        if request.permission_type == "webfetch" and self._webfetch_handler is not None:
            return await self._webfetch_handler(request.callback)

        return ACPPermissionDecision(
            request_id=request.id,
            granted=False,
            reason="No handler registered for permission type",
        )


class PermissionBrokerFactory:
    """Factory for creating permission brokers with common configurations."""

    _TRUSTED_INTERACTIVE_SESSION_PREFIXES = ("telegram:",)
    _UNATTENDED_SESSION_PREFIXES = ("cron:",)
    _UNATTENDED_SESSION_KEYS = {"heartbeat"}

    @classmethod
    def is_trusted_interactive_session(cls, session_key: str) -> bool:
        """Return True only for trusted Telegram chat sessions.

        `interactive=True` is reserved for the current trusted Telegram control
        plane. Cron, heartbeat, and other non-Telegram surfaces stay on
        `interactive=False` so `policy="auto"` cannot silently widen approval-
        free execution beyond the intended channel.
        """
        return session_key.startswith(cls._TRUSTED_INTERACTIVE_SESSION_PREFIXES)

    @classmethod
    def create_for_session(
        cls,
        session_key: str,
        *,
        agent_policy: str = "auto",
        permission_policies: Optional[dict[str, str]] = None,
        callback_registry: Optional[ACPCallbackRegistry] = None,
        timeout: Optional[float] = None,
    ) -> ACPPermissionBroker:
        """Create a broker for a specific nanobot session key.

        Trusted interactive chat sessions resolve `policy="auto"` to allow by
        default without prompting. Cron and other unattended sessions keep
        `interactive=False` and use unattended policy defaults instead.
        """
        interactive = cls.is_trusted_interactive_session(session_key)
        policy = cls._build_session_policy(
            interactive=interactive,
            agent_policy=agent_policy,
            permission_policies=permission_policies,
        )
        return cls.create_from_config(
            interactive=interactive,
            callback_registry=callback_registry,
            policy=policy,
            timeout=timeout,
        )

    @classmethod
    def _build_session_policy(
        cls,
        *,
        interactive: bool,
        agent_policy: str,
        permission_policies: Optional[dict[str, str]] = None,
    ) -> UnattendedPermissionPolicy:
        default_mode = cls._resolve_runtime_mode(agent_policy, interactive=interactive)
        overrides: dict[str, PermissionMode] = {}

        for action, configured_mode in (permission_policies or {}).items():
            resolved_mode = cls._resolve_runtime_mode(
                configured_mode,
                interactive=interactive,
                fallback=default_mode,
            )
            if action in {"default", "*"}:
                default_mode = resolved_mode
                continue
            overrides[action] = resolved_mode

        return UnattendedPermissionPolicy(
            default_mode=default_mode,
            action_overrides=overrides,
        )

    @staticmethod
    def _resolve_runtime_mode(
        configured_mode: str,
        *,
        interactive: bool,
        fallback: PermissionMode = "deny",
    ) -> PermissionMode:
        if configured_mode not in RUNTIME_PERMISSION_POLICIES:
            return fallback
        if configured_mode == "auto":
            return cast(PermissionMode, "allow" if interactive else "deny")
        return cast(PermissionMode, configured_mode)

    @staticmethod
    def create_interactive(
        callback_registry: Optional[ACPCallbackRegistry] = None,
        timeout: float = 30.0,
        policy: Optional[UnattendedPermissionPolicy] = None,
    ) -> ACPPermissionBroker:
        """Create an interactive permission broker.

        Args:
            callback_registry: Registry for permission callbacks.
            timeout: Timeout for permission requests.

        Returns:
            Configured interactive permission broker.
        """
        return ACPPermissionBroker(
            callback_registry=callback_registry,
            interactive=True,
            policy=policy,
            timeout=timeout,
        )

    @staticmethod
    def create_unattended(
        policy: Optional[UnattendedPermissionPolicy] = None,
    ) -> ACPPermissionBroker:
        """Create an unattended permission broker.

        Args:
            policy: Policy for permission resolution.

        Returns:
            Configured unattended permission broker.
        """
        return ACPPermissionBroker(
            callback_registry=None,
            interactive=False,
            policy=policy,
        )

    @staticmethod
    def create_from_config(
        interactive: bool,
        callback_registry: Optional[ACPCallbackRegistry] = None,
        policy: Optional[UnattendedPermissionPolicy] = None,
        timeout: Optional[float] = None,
    ) -> ACPPermissionBroker:
        """Create a permission broker from configuration.

        Args:
            interactive: Whether to run in interactive mode.
            callback_registry: Optional callback registry.
            policy: Optional policy for unattended mode.
            timeout: Optional timeout value.

        Returns:
            Configured permission broker.
        """
        return ACPPermissionBroker(
            callback_registry=callback_registry,
            interactive=interactive,
            policy=policy,
            timeout=timeout,
        )
