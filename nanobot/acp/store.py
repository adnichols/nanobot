"""ACP session store implementation.

This module provides a durable ACPSessionStore implementation that persists
ACP session records to disk. It implements the ACPSessionStore protocol from
nanobot.acp.interfaces.

The store is designed to survive process restarts and be used by downstream
tracks (ACP-03, ACP-08, ACP-09, ACP-10).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from nanobot.acp.types import ACPSessionRecord
from nanobot.utils.helpers import ensure_dir


class ACPFileSessionStore:
    """File-based ACPSessionStore implementation.

    Persists ACP session records as JSON files in a storage directory.
    Sessions are stored with their ID as the filename.

    Intentionally deferred fields in ACPSessionRecord:
    - active_tool_use_id: Not currently persisted as it represents runtime state
    - These can be added when needed by downstream tracks
    """

    def __init__(self, storage_dir: Path):
        """Initialize the session store.

        Args:
            storage_dir: Directory where session files will be stored.
        """
        self.storage_dir = ensure_dir(storage_dir)

    def _get_session_path(self, session_id: str) -> Path:
        """Get the file path for a session."""
        # Sanitize session ID for use as filename
        safe_id = session_id.replace("/", "_").replace("\\", "_")
        return self.storage_dir / f"{safe_id}.json"

    async def save(self, session: ACPSessionRecord) -> None:
        """Save a session record to persistent storage.

        Args:
            session: The session record to save.
        """
        path = self._get_session_path(session.id)
        data = session.to_dict()

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    async def load(self, session_id: str) -> Optional[ACPSessionRecord]:
        """Load a session by ID.

        Args:
            session_id: The ID of the session to load.

        Returns:
            The session record if found, None otherwise.
        """
        path = self._get_session_path(session_id)

        if not path.exists():
            return None

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return ACPSessionRecord.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Log but don't fail - corrupted sessions are skipped
            import logging

            logging.warning(f"Failed to load session {session_id}: {e}")
            return None

    async def delete(self, session_id: str) -> None:
        """Delete a session by ID.

        Args:
            session_id: The ID of the session to delete.
        """
        path = self._get_session_path(session_id)

        if path.exists():
            path.unlink()

    async def list_sessions(self) -> list[ACPSessionRecord]:
        """List all available sessions.

        Returns:
            List of all stored session records.
        """
        sessions = []

        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append(ACPSessionRecord.from_dict(data))
            except (json.JSONDecodeError, KeyError, ValueError):
                # Skip corrupted session files
                continue

        # Sort by updated_at descending
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions


class ACPSessionBinding:
    """Binding between a nanobot session and an ACP session.

    This class represents the correlation between a nanobot conversation
    session (identified by channel:chat_id) and an ACP agent session.
    It's used to recover ACP sessions after process restarts.
    """

    def __init__(
        self,
        nanobot_session_key: str,
        acp_agent_id: str,
        acp_session_id: str,
        cwd: str | None = None,
        metadata: dict | None = None,
        capabilities: list[str] | None = None,
    ):
        """Create a session binding.

        Args:
            nanobot_session_key: The nanobot session key (e.g., "telegram:12345")
            acp_agent_id: The ACP agent definition ID
            acp_session_id: The ACP session ID
            cwd: Working directory for the ACP session
            metadata: Additional metadata (e.g., capability config)
            capabilities: List of capabilities enabled for this session
        """
        self.nanobot_session_key = nanobot_session_key
        self.acp_agent_id = acp_agent_id
        self.acp_session_id = acp_session_id
        self.cwd = cwd
        self.metadata = metadata or {}
        self.capabilities = capabilities or []

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "nanobot_session_key": self.nanobot_session_key,
            "acp_agent_id": self.acp_agent_id,
            "acp_session_id": self.acp_session_id,
            "cwd": self.cwd,
            "metadata": self.metadata,
            "capabilities": self.capabilities,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ACPSessionBinding:
        """Deserialize from dictionary."""
        return cls(
            nanobot_session_key=data["nanobot_session_key"],
            acp_agent_id=data["acp_agent_id"],
            acp_session_id=data["acp_session_id"],
            cwd=data.get("cwd"),
            metadata=data.get("metadata", {}),
            capabilities=data.get("capabilities", []),
        )


class ACPSessionBindingStore:
    """Store for session bindings.

    This store maintains the correlation between nanobot sessions and
    ACP sessions, enabling session recovery after restarts.
    """

    def __init__(self, storage_dir: Path):
        """Initialize the binding store.

        Args:
            storage_dir: Directory where binding files will be stored.
        """
        self.storage_dir = ensure_dir(storage_dir)
        self._bindings_file = self.storage_dir / "bindings.json"
        self._bindings: dict[str, ACPSessionBinding] = {}
        self._load_bindings()

    def _load_bindings(self) -> None:
        """Load bindings from disk."""
        if not self._bindings_file.exists():
            return

        try:
            with open(self._bindings_file, encoding="utf-8") as f:
                data = json.load(f)
            self._bindings = {
                key: ACPSessionBinding.from_dict(value) for key, value in data.items()
            }
        except (json.JSONDecodeError, ValueError):
            self._bindings = {}

    def _save_bindings(self) -> None:
        """Save bindings to disk."""
        data = {key: binding.to_dict() for key, binding in self._bindings.items()}
        with open(self._bindings_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save_binding(self, binding: ACPSessionBinding) -> None:
        """Save a session binding.

        Args:
            binding: The session binding to save.
        """
        self._bindings[binding.nanobot_session_key] = binding
        self._save_bindings()

    def load_binding(self, nanobot_session_key: str) -> Optional[ACPSessionBinding]:
        """Load a session binding by nanobot session key.

        Args:
            nanobot_session_key: The nanobot session key.

        Returns:
            The binding if found, None otherwise.
        """
        return self._bindings.get(nanobot_session_key)

    def delete_binding(self, nanobot_session_key: str) -> None:
        """Delete a session binding.

        Args:
            nanobot_session_key: The nanobot session key.
        """
        self._bindings.pop(nanobot_session_key, None)
        self._save_bindings()

    def list_bindings(self) -> list[ACPSessionBinding]:
        """List all session bindings.

        Returns:
            List of all stored bindings.
        """
        return list(self._bindings.values())
