"""ACP (Agent Communication Protocol) shared types and interfaces."""

from nanobot.acp.contracts import (
    ACPContract,
    ACPContractViolation,
)
from nanobot.acp.interfaces import (
    ACPCallbackRegistry,
    ACPPermissionDecision,
    ACPPermissionRequest,
    ACPRenderEvent,
    ACPSessionStore,
    ACPUpdateSink,
)
from nanobot.acp.sdk_client import SDKClient
from nanobot.acp.service import ACPService, ACPServiceConfig
from nanobot.acp.session import ACPSession, ACPSessionManager
from nanobot.acp.types import (
    ACPFilesystemCallback,
    ACPMessageType,
    ACPRenderedUpdate,
    ACPSessionRecord,
    ACPStreamChunk,
    ACPTerminalCallback,
    ACPUpdateEvent,
)

__all__ = [
    # Types
    "ACPSessionRecord",
    "ACPUpdateEvent",
    "ACPRenderedUpdate",
    "ACPFilesystemCallback",
    "ACPTerminalCallback",
    "ACPMessageType",
    "ACPStreamChunk",
    # Interfaces
    "ACPSessionStore",
    "ACPCallbackRegistry",
    "ACPUpdateSink",
    "ACPRenderEvent",
    "ACPPermissionRequest",
    "ACPPermissionDecision",
    # Contracts
    "ACPContract",
    "ACPContractViolation",
    # SDK Client
    "SDKClient",
    # Service
    "ACPService",
    "ACPServiceConfig",
    # Session
    "ACPSession",
    "ACPSessionManager",
]
