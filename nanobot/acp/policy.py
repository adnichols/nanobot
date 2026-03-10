"""Unattended permission policy model.

This module defines a small, deterministic policy for resolving permission
requests in non-interactive (unattended/cron) automation scenarios.

The policy model is consumed by:
- ACP-06 (permission broker) - for runtime resolution
- ACP-09 (scheduler) - for cron-triggered sessions
- ACP-10 (routing) - for determining default behavior

Policy design:
- Explicit default behavior (allow/deny/ask)
- Per-action overrides keyed by ACP action or tool identity
- Small and deterministic - no complex logic or external calls
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# Type aliases for policy modes
PermissionMode = Literal["allow", "deny", "ask"]


@dataclass(frozen=True)
class UnattendedPermissionPolicy:
    """Unattended permission policy for automation scenarios.

    This policy defines how permission requests are resolved when running
    in non-interactive mode (e.g., cron-triggered ACP sessions).

    Attributes:
        default_mode: The default permission mode when no override applies.
            - "allow": Automatically grant all permission requests
            - "deny": Automatically deny all permission requests
            - "ask": Attempt to use callback handler (will timeout if no handler)
        action_overrides: Optional per-action overrides keyed by action name
            (e.g., "filesystem:read", "terminal:bash"). Override values must be
            "allow", "deny", or "ask".
    """

    default_mode: PermissionMode = "deny"
    action_overrides: dict[str, PermissionMode] = field(default_factory=dict)

    def resolve(self, action: str) -> PermissionMode:
        """Resolve the permission mode for a given action.

        Args:
            action: The action or tool name to resolve permissions for
                (e.g., "filesystem:read", "bash", "grep").

        Returns:
            The resolved permission mode ("allow", "deny", or "ask").
        """
        # Check for exact action override first
        if action in self.action_overrides:
            return self.action_overrides[action]

        # Check for partial match (action starts with override key)
        for override_key, mode in self.action_overrides.items():
            if action.startswith(override_key):
                return mode

        # Fall back to default mode
        return self.default_mode

    def is_allowed(self, action: str) -> bool:
        """Check if an action is allowed by this policy.

        Args:
            action: The action to check.

        Returns:
            True if the resolved mode is "allow", False otherwise.
        """
        return self.resolve(action) == "allow"

    def is_denied(self, action: str) -> bool:
        """Check if an action is denied by this policy.

        Args:
            action: The action to check.

        Returns:
            True if the resolved mode is "deny", False otherwise.
        """
        return self.resolve(action) == "deny"

    def requires_ask(self, action: str) -> bool:
        """Check if an action requires interactive approval.

        Args:
            action: The action to check.

        Returns:
            True if the resolved mode is "ask", False otherwise.
        """
        return self.resolve(action) == "ask"


# Pre-defined policy instances for common scenarios
class PolicyDefaults:
    """Pre-configured policy instances for common use cases."""

    # Allow all permissions (use with caution - for trusted agents only)
    PERMISSIVE = UnattendedPermissionPolicy(default_mode="allow")

    # Deny all permissions by default (most secure)
    RESTRICTIVE = UnattendedPermissionPolicy(default_mode="deny")

    # Ask for permissions, requires callback handler
    CONSERVATIVE = UnattendedPermissionPolicy(default_mode="ask")

    @classmethod
    def create_custom(
        cls,
        default_mode: PermissionMode = "deny",
        allow_actions: Optional[list[str]] = None,
        deny_actions: Optional[list[str]] = None,
        ask_actions: Optional[list[str]] = None,
    ) -> UnattendedPermissionPolicy:
        """Create a custom policy with categorized actions.

        Args:
            default_mode: The default permission mode.
            allow_actions: List of actions to allow.
            deny_actions: List of actions to deny.
            ask_actions: List of actions to require approval for.

        Returns:
            A new UnattendedPermissionPolicy instance.
        """
        overrides: dict[str, PermissionMode] = {}

        if allow_actions:
            for action in allow_actions:
                overrides[action] = "allow"

        if deny_actions:
            for action in deny_actions:
                overrides[action] = "deny"

        if ask_actions:
            for action in ask_actions:
                overrides[action] = "ask"

        return UnattendedPermissionPolicy(
            default_mode=default_mode,
            action_overrides=overrides,
        )
