"""Shared ACP types for runtime, session records, callbacks, and update events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, Optional


class ACPMessageType(Enum):
    """Message types in the ACP protocol."""

    TEXT = auto()
    TOOL_USE = auto()
    TOOL_RESULT = auto()
    STOP = auto()
    ERROR = auto()


class ACPStreamChunkType(Enum):
    """Types of streaming chunks."""

    CONTENT_DELTA = auto()
    TOOL_USE_START = auto()
    TOOL_USE_END = auto()
    TOOL_RESULT_START = auto()
    TOOL_RESULT_END = auto()
    DONE = auto()
    ERROR = auto()


@dataclass
class ACPStreamChunk:
    """A chunk of streamed content from the ACP agent."""

    type: ACPStreamChunkType
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_result_id: Optional[str] = None
    tool_result_content: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ACPSessionRecord:
    """A persisted ACP session that can be resumed."""

    id: str
    created_at: datetime
    updated_at: datetime
    state: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    active_tool_use_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "state": self.state,
            "messages": self.messages,
            "active_tool_use_id": self.active_tool_use_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ACPSessionRecord:
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            state=data.get("state", {}),
            messages=data.get("messages", []),
            active_tool_use_id=data.get("active_tool_use_id"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ACPUpdateEvent:
    """An update event emitted by the ACP runtime."""

    event_type: str
    timestamp: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None


@dataclass
class ACPRenderedUpdate:
    """A rendered update ready for display or transmission."""

    update_type: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ACPFilesystemCallback:
    """Callback data for filesystem operations requiring permission."""

    operation: str  # "read", "write", "delete", "list", etc.
    path: str
    content: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ACPTerminalCallback:
    """Callback data for terminal/sudo operations requiring permission."""

    command: str
    working_directory: Optional[str] = None
    environment: dict[str, str] = field(default_factory=dict)
    timeout: Optional[float] = None


@dataclass
class ACPPermissionRequest:
    """A permission request from the ACP agent."""

    id: str
    permission_type: str  # "filesystem", "terminal", "webfetch", etc.
    description: str
    resource: str  # what the permission is for
    callback: Any = field(default=None)  # The actual callback object (FilesystemCallback, etc.)
    correlation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_decision(self, granted: bool, reason: Optional[str] = None) -> ACPPermissionDecision:
        """Create a decision from this request."""
        return ACPPermissionDecision(
            request_id=self.id,
            granted=granted,
            reason=reason,
            timestamp=datetime.now(UTC),
        )


@dataclass
class ACPPermissionDecision:
    """A permission decision response."""

    request_id: str
    granted: bool
    reason: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ACPToolDefinition:
    """Definition of a tool available to the ACP agent."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class ACPInitializeRequest:
    """Request to initialize an ACP agent session."""

    session_id: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: list[ACPToolDefinition] = field(default_factory=list)
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None


@dataclass
class ACPPromptRequest:
    """Request to send a prompt to the ACP agent."""

    content: str
    session_id: str


@dataclass
class ACPCancelRequest:
    """Request to cancel an ongoing ACP operation."""

    session_id: str
    operation_id: Optional[str] = None


@dataclass
class ACPLoadSessionRequest:
    """Request to load a persisted ACP session."""

    session_id: str
