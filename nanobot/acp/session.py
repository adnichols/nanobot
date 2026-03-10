"""ACP session management wrapper.

This module provides a wrapper for ACP sessions that integrates with
the ACPSessionStore contract from ACP-02. It handles session binding
persistence and provides a clean interface for session operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from nanobot.acp.interfaces import ACPSessionStore
from nanobot.acp.store import ACPSessionBinding
from nanobot.acp.types import ACPSessionRecord


@dataclass
class ACPSession:
    """ACP session wrapper.

    Provides a high-level interface for ACP session operations,
    including binding to nanobot sessions and persistence.
    """

    session_id: str
    nanobot_session_key: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    _session_store: Optional[ACPSessionStore] = field(default=None, repr=False)

    def __post_init__(self):
        """Post-initialization processing."""
        if self._session_store is None:
            # Try to get default session store
            pass  # Will be set when attached to a store

    def attach_store(self, store: ACPSessionStore) -> None:
        """Attach a session store for persistence.

        Args:
            store: The session store to use.
        """
        self._session_store = store

    async def save(self) -> None:
        """Save the session to the attached store.

        Raises:
            RuntimeError: If no session store is attached.
        """
        if self._session_store is None:
            raise RuntimeError("No session store attached")

        record = self.to_record()
        await self._session_store.save(record)
        self.updated_at = datetime.now(UTC)

    @classmethod
    async def load(cls, session_id: str, store: ACPSessionStore) -> Optional["ACPSession"]:
        """Load a session from the store.

        Args:
            session_id: The session ID to load.
            store: The session store to load from.

        Returns:
            The loaded session or None if not found.
        """
        record = await store.load(session_id)
        if record is None:
            return None

        return cls(
            session_id=record.id,
            nanobot_session_key=record.metadata.get("nanobot_session_key"),
            created_at=record.created_at,
            updated_at=record.updated_at,
            state=record.state,
            messages=record.messages,
            metadata=record.metadata,
            _session_store=store,
        )

    def to_record(self) -> ACPSessionRecord:
        """Convert to an ACPSessionRecord for persistence.

        Returns:
            The session record.
        """
        return ACPSessionRecord(
            id=self.session_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            state=self.state,
            messages=self.messages,
            active_tool_use_id=self.metadata.get("active_tool_use_id"),
            metadata={
                **self.metadata,
                "nanobot_session_key": self.nanobot_session_key,
            },
        )

    def get_binding(self) -> Optional[dict[str, Any]]:
        """Get the session binding as a dict.

        Returns:
            Binding dict with nanobot correlation, or None.
        """
        if not self.nanobot_session_key:
            return None

        return {
            "nanobot_session_key": self.nanobot_session_key,
            "acp_session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_binding(
        cls,
        binding: ACPSessionBinding,
        store: Optional[ACPSessionStore] = None,
    ) -> "ACPSession":
        """Create a session from a binding.

        Args:
            binding: The session binding.
            store: Optional session store.

        Returns:
            New ACPSession instance.
        """
        return cls(
            session_id=binding.acp_session_id,
            nanobot_session_key=binding.nanobot_session_key,
            metadata=binding.metadata,
            _session_store=store,
        )

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the session.

        Args:
            role: Message role (user, assistant, system).
            content: Message content.
        """
        self.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        self.updated_at = datetime.now(UTC)

    def get_messages(self) -> list[dict[str, Any]]:
        """Get all messages in the session.

        Returns:
            List of message dicts.
        """
        return self.messages.copy()

    def update_state(self, key: str, value: Any) -> None:
        """Update session state.

        Args:
            key: State key.
            value: State value.
        """
        self.state[key] = value
        self.updated_at = datetime.now(UTC)

    def get_state(self, key: str, default: Any = None) -> Any:
        """Get a state value.

        Args:
            key: State key.
            default: Default value if key not found.

        Returns:
            The state value or default.
        """
        return self.state.get(key, default)

    def clear_state(self) -> None:
        """Clear all session state."""
        self.state.clear()
        self.updated_at = datetime.now(UTC)


class ACPSessionManager:
    """Manager for multiple ACP sessions.

    Provides centralized session management with binding support.
    """

    def __init__(self, session_store: Optional[ACPSessionStore] = None):
        """Initialize the session manager.

        Args:
            session_store: The session store to use.
        """
        self._session_store = session_store
        self._sessions: dict[str, ACPSession] = {}

    def create_session(
        self,
        session_id: str,
        nanobot_session_key: Optional[str] = None,
    ) -> ACPSession:
        """Create a new session.

        Args:
            session_id: The session ID.
            nanobot_session_key: Optional nanobot session key for binding.

        Returns:
            The created session.
        """
        session = ACPSession(
            session_id=session_id,
            nanobot_session_key=nanobot_session_key,
            _session_store=self._session_store,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[ACPSession]:
        """Get a session by ID.

        Args:
            session_id: The session ID.

        Returns:
            The session or None if not found.
        """
        return self._sessions.get(session_id)

    async def load_session(self, session_id: str) -> Optional[ACPSession]:
        """Load a session from the store.

        Args:
            session_id: The session ID.

        Returns:
            The loaded session or None.
        """
        if self._session_store is None:
            return None

        session = await ACPSession.load(session_id, self._session_store)
        if session:
            self._sessions[session_id] = session
        return session

    def remove_session(self, session_id: str) -> None:
        """Remove a session from the manager.

        Args:
            session_id: The session ID.
        """
        self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[ACPSession]:
        """List all managed sessions.

        Returns:
            List of sessions.
        """
        return list(self._sessions.values())

    @property
    def session_count(self) -> int:
        """Get the number of active sessions."""
        return len(self._sessions)
