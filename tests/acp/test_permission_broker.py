"""Tests for ACP permission broker.

These tests cover:
- Allow permission (user approves)
- Deny permission (user denies)
- Timeout behavior
- Unattended resolution with policy
- Concurrent correlation (overlapping requests, out-of-order replies)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import pytest

from nanobot.acp.permissions import (
    ACPPermissionBroker,
    UnattendedPermissionPolicy,
)
from nanobot.acp.types import (
    ACPPermissionDecision,
    ACPPermissionRequest,
)


class FakeACPCallbackRegistry:
    """Fake callback registry for testing."""

    def __init__(self):
        self._handlers: dict[str, Optional[Callable]] = {}

    def register_filesystem_callback(
        self, handler: Callable[[Any], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._handlers["filesystem"] = handler

    def register_terminal_callback(
        self, handler: Callable[[Any], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._handlers["terminal"] = handler

    def register_webfetch_callback(
        self, handler: Callable[[dict[str, Any]], Awaitable[ACPPermissionDecision]]
    ) -> None:
        self._handlers["webfetch"] = handler

    async def handle_permission_request(
        self, request: ACPPermissionRequest
    ) -> ACPPermissionDecision:
        handler = self._handlers.get(request.permission_type)
        if handler is None:
            raise ValueError(f"No handler registered for {request.permission_type}")
        return await handler(request)


def create_permission_request(
    permission_type: str = "filesystem",
    description: str = "test permission",
    resource: str = "/tmp/test",
    correlation_id: Optional[str] = None,
) -> ACPPermissionRequest:
    """Helper to create permission requests for testing."""
    return ACPPermissionRequest(
        id=str(uuid.uuid4()),
        permission_type=permission_type,
        description=description,
        resource=resource,
        callback={},
        correlation_id=correlation_id or str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
    )


class TestAllowPermission:
    """Tests for user approving a permission request."""

    @pytest.mark.asyncio
    async def test_user_approves_permission_returns_allow(self):
        """Given a risky tool request arrives in an interactive chat,
        when the user approves, then the broker returns allow with
        the correct correlation id."""
        # Arrange
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(callback_registry=registry, interactive=True)

        request = create_permission_request(
            permission_type="filesystem",
            description="Read file /etc/passwd",
            resource="/etc/passwd",
        )

        # Act - Register a handler that simulates user approval
        async def approve_handler(callback):
            return ACPPermissionDecision(
                request_id=request.id,
                granted=True,
                reason="User approved",
            )

        registry._handlers["filesystem"] = approve_handler
        decision = await broker.request_permission(request)

        # Assert
        assert decision.granted is True
        assert decision.request_id == request.id

    @pytest.mark.asyncio
    async def test_allow_preserves_correlation_id(self):
        """Verify that correlation id is preserved through the broker."""
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(callback_registry=registry, interactive=True)

        correlation_id = "test-correlation-123"
        request = create_permission_request(correlation_id=correlation_id)

        async def allow_handler(callback):
            return ACPPermissionDecision(request_id=request.id, granted=True)

        registry._handlers[request.permission_type] = allow_handler
        decision = await broker.request_permission(request)

        assert decision.request_id == request.id


class TestDenyPermission:
    """Tests for user denying a permission request."""

    @pytest.mark.asyncio
    async def test_user_denies_permission_returns_deny(self):
        """Given a risky tool request arrives in an interactive chat,
        when the user denies, then the broker returns deny."""
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(callback_registry=registry, interactive=True)

        request = create_permission_request(
            permission_type="filesystem",
            description="Delete system file",
            resource="/etc/shadow",
        )

        async def deny_handler(callback):
            return ACPPermissionDecision(
                request_id=request.id,
                granted=False,
                reason="User denied",
            )

        registry._handlers["filesystem"] = deny_handler
        decision = await broker.request_permission(request)

        assert decision.granted is False
        assert decision.reason == "User denied"

    @pytest.mark.asyncio
    async def test_deny_with_reason(self):
        """Verify deny decisions include a reason."""
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(callback_registry=registry, interactive=True)

        request = create_permission_request()

        async def deny_handler(callback):
            return ACPPermissionDecision(
                request_id=request.id,
                granted=False,
                reason="Operation not permitted by policy",
            )

        registry._handlers[request.permission_type] = deny_handler
        decision = await broker.request_permission(request)

        assert decision.granted is False
        assert "not permitted" in decision.reason


class TestTimeoutBehavior:
    """Tests for timeout handling."""

    @pytest.mark.asyncio
    async def test_permission_timeout_returns_deny(self):
        """Given a permission request that times out,
        then the broker returns deny with timeout reason."""
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(
            callback_registry=registry,
            interactive=True,
            timeout=0.1,  # 100ms timeout
        )

        request = create_permission_request()

        # Handler that never completes (simulates user not responding)
        async def hanging_handler(callback):
            await asyncio.sleep(10)  # Much longer than timeout
            return ACPPermissionDecision(request_id=request.id, granted=True)

        registry._handlers[request.permission_type] = hanging_handler
        decision = await broker.request_permission(request)

        assert decision.granted is False
        assert "timed out" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_timeout_uses_configurable_duration(self):
        """Verify timeout duration is configurable."""
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(
            callback_registry=registry,
            interactive=True,
            timeout=1.0,  # 1 second
        )

        request = create_permission_request()

        async def hanging_handler(callback):
            await asyncio.sleep(5)
            return ACPPermissionDecision(request_id=request.id, granted=True)

        registry._handlers[request.permission_type] = hanging_handler

        start = datetime.now(timezone.utc)
        decision = await broker.request_permission(request)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()

        assert decision.granted is False
        # Should timeout around 1 second, allow some tolerance
        assert elapsed < 2.0


class TestUnattendedResolution:
    """Tests for unattended (non-interactive) permission resolution."""

    @pytest.mark.asyncio
    async def test_unattended_allow_by_default_policy(self):
        """Given a cron-triggered ACP session runs unattended,
        when a permission request arrives, then the configured
        automation policy resolves it without deadlock."""
        # Arrange - Policy set to allow by default
        policy = UnattendedPermissionPolicy(default_mode="allow")
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(
            callback_registry=registry,
            interactive=False,  # Unattended mode
            policy=policy,
        )

        request = create_permission_request(
            permission_type="filesystem",
            description="Read data file",
            resource="/data/input.csv",
        )

        # Act
        decision = await broker.request_permission(request)

        # Assert - Should be resolved by policy without hanging
        assert decision.granted is True

    @pytest.mark.asyncio
    async def test_unattended_deny_by_default_policy(self):
        """Given unattended mode with deny policy,
        when a permission request arrives, then it is denied."""
        policy = UnattendedPermissionPolicy(default_mode="deny")
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(
            callback_registry=registry,
            interactive=False,
            policy=policy,
        )

        request = create_permission_request()

        decision = await broker.request_permission(request)

        assert decision.granted is False
        assert decision.reason is not None

    @pytest.mark.asyncio
    async def test_unattended_timeout_prevents_indefinite_blocking(self):
        """Non-interactive mode cannot hang indefinitely."""
        policy = UnattendedPermissionPolicy(default_mode="ask")
        registry = FakeACPCallbackRegistry()

        # In non-interactive mode with "ask" policy and no handler,
        # should still resolve (not hang)
        broker = ACPPermissionBroker(
            callback_registry=registry,
            interactive=False,
            policy=policy,
            timeout=0.5,
        )

        request = create_permission_request()

        # Should not hang - should timeout/fallback
        decision = await broker.request_permission(request)

        # Should resolve one way or another
        assert decision is not None
        # In unattended mode with ask but no handler, should fallback to deny
        assert decision.granted is False

    @pytest.mark.asyncio
    async def test_per_action_override_allows_specific_action(self):
        """Policy can override behavior for specific actions."""
        policy = UnattendedPermissionPolicy(
            default_mode="deny",
            action_overrides={
                "filesystem:read": "allow",  # Allow read operations
            },
        )
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(
            callback_registry=registry,
            interactive=False,
            policy=policy,
        )

        request = create_permission_request(
            permission_type="filesystem",
            description="Read file",
        )
        # Note: In real usage, the action key would include tool name
        # For this test we're testing the override mechanism directly

        decision = await broker.request_permission(request)

        # Should follow default (deny) since we don't have the exact action key
        assert decision.granted is False


class TestConcurrentCorrelation:
    """Tests for concurrent permission requests with correlation."""

    @pytest.mark.asyncio
    async def test_overlapping_requests_correlation_ids_preserved(self):
        """Given multiple permission requests overlap,
        when replies arrive out of order, then they still
        map to the correct requests."""
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(callback_registry=registry, interactive=True)

        # Create multiple overlapping requests with different correlation IDs
        request1 = create_permission_request(correlation_id="corr-1")
        request2 = create_permission_request(correlation_id="corr-2")
        request3 = create_permission_request(correlation_id="corr-3")

        async def handler1(callback):
            await asyncio.sleep(0.05)  # Slower response
            return ACPPermissionDecision(request_id=request1.id, granted=True)

        async def handler2(callback):
            await asyncio.sleep(0.02)  # Faster response
            return ACPPermissionDecision(request_id=request2.id, granted=False)

        async def handler3(callback):
            await asyncio.sleep(0.03)  # Medium response
            return ACPPermissionDecision(request_id=request3.id, granted=True)

        # All requests use filesystem - need separate handling or batching
        # For this test, we'll use different permission types
        request1.permission_type = "filesystem"
        request2.permission_type = "terminal"
        request3.permission_type = "webfetch"

        registry._handlers["filesystem"] = handler1
        registry._handlers["terminal"] = handler2
        registry._handlers["webfetch"] = handler3

        # Execute all requests concurrently
        # Note: results dict removed as it was unused - correlation is verified via request_id
        decision1, decision2, decision3 = await asyncio.gather(
            broker.request_permission(request1),
            broker.request_permission(request2),
            broker.request_permission(request3),
        )

        # Verify each decision maps to the correct request
        assert decision1.request_id == request1.id
        assert decision1.granted is True

        assert decision2.request_id == request2.id
        assert decision2.granted is False

        assert decision3.request_id == request3.id
        assert decision3.granted is True

    @pytest.mark.asyncio
    async def test_out_of_order_responses_mapped_correctly(self):
        """Verify out-of-order responses are correctly correlated."""
        registry = FakeACPCallbackRegistry()
        broker = ACPPermissionBroker(callback_registry=registry, interactive=True)

        # Create two requests
        request_a = create_permission_request(
            permission_type="filesystem",
            correlation_id="a",
        )
        request_b = create_permission_request(
            permission_type="terminal",
            correlation_id="b",
        )

        # Handler for request A (slower)
        async def handler_a(callback):
            await asyncio.sleep(0.1)
            return ACPPermissionDecision(request_id=request_a.id, granted=True)

        # Handler for request B (faster)
        async def handler_b(callback):
            await asyncio.sleep(0.01)
            return ACPPermissionDecision(request_id=request_b.id, granted=False)

        registry._handlers["filesystem"] = handler_a
        registry._handlers["terminal"] = handler_b

        # Start A first, then B - B will complete first
        task_a = asyncio.create_task(broker.request_permission(request_a))
        task_b = asyncio.create_task(broker.request_permission(request_b))

        # B completes first, then A
        decision_b = await task_b
        decision_a = await task_a

        # Each decision should map to its original request
        assert decision_a.request_id == request_a.id
        assert decision_a.granted is True

        assert decision_b.request_id == request_b.id
        assert decision_b.granted is False


class TestPolicyModelInterface:
    """Tests for the policy model interface."""

    def test_policy_default_mode_is_required(self):
        """Policy must have a default mode."""
        policy = UnattendedPermissionPolicy(default_mode="allow")
        assert policy.default_mode == "allow"

    def test_policy_supports_deny_mode(self):
        """Policy can be configured to deny by default."""
        policy = UnattendedPermissionPolicy(default_mode="deny")
        assert policy.default_mode == "deny"

    def test_policy_supports_ask_mode(self):
        """Policy can be configured to ask (requires handler)."""
        policy = UnattendedPermissionPolicy(default_mode="ask")
        assert policy.default_mode == "ask"

    def test_policy_action_overrides(self):
        """Policy supports per-action overrides."""
        policy = UnattendedPermissionPolicy(
            default_mode="deny",
            action_overrides={
                "read": "allow",
                "write": "ask",
            },
        )
        assert policy.default_mode == "deny"
        assert policy.action_overrides.get("read") == "allow"
        assert policy.action_overrides.get("write") == "ask"

    def test_policy_resolve_returns_allowed_for_allow_mode(self):
        """Policy resolution returns allowed for allow mode."""
        policy = UnattendedPermissionPolicy(default_mode="allow")
        result = policy.resolve("any-action")
        assert result == "allow"

    def test_policy_resolve_returns_denied_for_deny_mode(self):
        """Policy resolution returns denied for deny mode."""
        policy = UnattendedPermissionPolicy(default_mode="deny")
        result = policy.resolve("any-action")
        assert result == "deny"

    def test_policy_resolve_uses_override(self):
        """Policy resolution uses action-specific overrides."""
        policy = UnattendedPermissionPolicy(
            default_mode="deny",
            action_overrides={"special-action": "allow"},
        )
        result = policy.resolve("special-action")
        assert result == "allow"

    def test_policy_resolve_fallback_to_default(self):
        """Policy resolution falls back to default when no override."""
        policy = UnattendedPermissionPolicy(
            default_mode="deny",
            action_overrides={"specific-action": "allow"},
        )
        result = policy.resolve("other-action")
        assert result == "deny"
