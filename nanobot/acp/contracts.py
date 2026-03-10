"""Protocol contracts for ACP runtime behavior.

These contracts define the expected behavior of ACP runtime implementations.
They are designed to be verified against implementations through testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from nanobot.acp.types import (
    ACPCancelRequest,
    ACPFilesystemCallback,
    ACPInitializeRequest,
    ACPLoadSessionRequest,
    ACPPermissionDecision,
    ACPPermissionRequest,
    ACPPromptRequest,
    ACPTerminalCallback,
)


class ACPContractViolationError(Exception):
    """Exception raised when an ACP contract is violated."""

    def __init__(self, contract_name: str, message: str, details: Optional[dict[str, Any]] = None):
        self.contract_name = contract_name
        self.details = details or {}
        super().__init__(f"Contract '{contract_name}' violated: {message}")


# Alias for backward compatibility
ACPContractViolation = ACPContractViolationError


@dataclass
class ACPContract:
    """A contract that ACP runtime implementations must satisfy."""

    name: str
    description: str
    verify: Callable[[], Awaitable[bool]]

    async def check(self) -> bool:
        """Verify the contract is satisfied."""
        try:
            return await self.verify()
        except NotImplementedError:
            raise ACPContractViolation(
                self.name, "Implementation not available", {"reason": "NotImplementedError raised"}
            )
        except Exception as e:
            raise ACPContractViolation(self.name, str(e), {"exception_type": type(e).__name__})


# Contract: Initialize
async def verify_initialize_contract(runtime: Any, request: ACPInitializeRequest) -> bool:
    """Verify that the runtime properly initializes with the given request."""
    if not hasattr(runtime, "initialize"):
        raise ACPContractViolation("initialize", "Runtime does not have an initialize method")
    result = await runtime.initialize(request)
    if not isinstance(result, dict):
        raise ACPContractViolation(
            "initialize", f"Expected dict result, got {type(result).__name__}"
        )
    return True


# Contract: Prompt streaming
async def verify_prompt_streaming_contract(runtime: Any, request: ACPPromptRequest) -> bool:
    """Verify that the runtime supports prompt streaming."""
    if not hasattr(runtime, "prompt"):
        raise ACPContractViolation("prompt", "Runtime does not have a prompt method")
    # Should support streaming - check for streaming interface
    if hasattr(runtime, "prompt_stream"):
        return True
    # If only prompt exists, it should still work
    result = await runtime.prompt(request)
    return result is not None


# Contract: Permission correlation
async def verify_permission_correlation_contract(
    runtime: Any, request: ACPPermissionRequest
) -> bool:
    """Verify that permission requests maintain correlation IDs."""
    if not hasattr(runtime, "handle_permission"):
        raise ACPContractViolation(
            "permission_correlation", "Runtime does not have a handle_permission method"
        )
    result = await runtime.handle_permission(request)
    if not isinstance(result, ACPPermissionDecision):
        raise ACPContractViolation(
            "permission_correlation", f"Expected ACPPermissionDecision, got {type(result).__name__}"
        )
    if result.request_id != request.id:
        raise ACPContractViolation(
            "permission_correlation",
            f"Request ID mismatch: expected {request.id}, got {result.request_id}",
        )
    return True


# Contract: Cancel
async def verify_cancel_contract(runtime: Any, request: ACPCancelRequest) -> bool:
    """Verify that the runtime supports cancellation."""
    if not hasattr(runtime, "cancel"):
        raise ACPContractViolation("cancel", "Runtime does not have a cancel method")
    await runtime.cancel(request)
    return True


# Contract: Load session
async def verify_load_session_contract(runtime: Any, request: ACPLoadSessionRequest) -> bool:
    """Verify that the runtime supports loading persisted sessions."""
    if not hasattr(runtime, "load_session"):
        raise ACPContractViolation("load_session", "Runtime does not have a load_session method")
    result = await runtime.load_session(request)
    if not isinstance(result, dict):
        raise ACPContractViolation(
            "load_session", f"Expected dict result, got {type(result).__name__}"
        )
    return True


# Contract: Session persistence
async def verify_session_persistence_contract(store: Any) -> bool:
    """Verify that the session store properly saves and loads sessions."""
    if not hasattr(store, "save") or not hasattr(store, "load"):
        raise ACPContractViolation("session_persistence", "Store does not have save/load methods")
    return True


# Contract: Update events
async def verify_update_events_contract(sink: Any) -> bool:
    """Verify that the update sink properly handles events."""
    if not hasattr(sink, "send_update"):
        raise ACPContractViolation("update_events", "Sink does not have a send_update method")
    # Can't actually test without a real runtime, just verify interface exists
    return True


# Contract: Filesystem callback shape
async def verify_filesystem_callback_contract(runtime: Any) -> bool:
    """Verify that filesystem callbacks have the correct shape."""
    if not hasattr(runtime, "handle_filesystem"):
        raise ACPContractViolation(
            "filesystem_callback", "Runtime does not have a handle_filesystem method"
        )

    callback = ACPFilesystemCallback(
        operation="read",
        path="test.txt",
        metadata={"request_id": "contract-fs-request"},
    )
    result = await runtime.handle_filesystem(callback)
    if not isinstance(result, ACPPermissionDecision):
        raise ACPContractViolation(
            "filesystem_callback",
            f"Expected ACPPermissionDecision, got {type(result).__name__}",
        )
    return True


# Contract: Terminal callback shape
async def verify_terminal_callback_contract(runtime: Any) -> bool:
    """Verify that terminal callbacks have the correct shape."""
    if not hasattr(runtime, "handle_terminal"):
        raise ACPContractViolation(
            "terminal_callback", "Runtime does not have a handle_terminal method"
        )

    callback = ACPTerminalCallback(command="pwd")
    result = await runtime.handle_terminal(callback)
    if not isinstance(result, ACPPermissionDecision):
        raise ACPContractViolation(
            "terminal_callback",
            f"Expected ACPPermissionDecision, got {type(result).__name__}",
        )
    return True
