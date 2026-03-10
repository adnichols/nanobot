"""Tests for ACP session store.

These tests verify that ACP session persistence works correctly,
survives restarts, and implements the shared ACPSessionStore contract.
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nanobot.acp.store import (
    ACPFileSessionStore,
    ACPSessionBinding,
    ACPSessionBindingStore,
)
from nanobot.acp.types import ACPSessionRecord


class TestACPSessionStoreContract:
    """Tests verifying the store implements the ACPSessionStore protocol."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a session store for testing."""
        return ACPFileSessionStore(storage_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_store_has_save_method(self, store):
        """Test that store has a save method."""
        assert hasattr(store, "save")
        assert callable(getattr(store, "save"))

    @pytest.mark.asyncio
    async def test_store_has_load_method(self, store):
        """Test that store has a load method."""
        assert hasattr(store, "load")
        assert callable(getattr(store, "load"))

    @pytest.mark.asyncio
    async def test_store_has_delete_method(self, store):
        """Test that store has a delete method."""
        assert hasattr(store, "delete")
        assert callable(getattr(store, "delete"))

    @pytest.mark.asyncio
    async def test_store_has_list_sessions_method(self, store):
        """Test that store has a list_sessions method."""
        assert hasattr(store, "list_sessions")
        assert callable(getattr(store, "list_sessions"))


class TestSessionPersistence:
    """Tests for session save/load/delete/list operations."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a session store for testing."""
        return ACPFileSessionStore(storage_dir=tmp_path)

    @pytest.fixture
    def sample_session(self):
        """Create a sample session record."""
        return ACPSessionRecord(
            id="test-session-123",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={"counter": 0},
            messages=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            active_tool_use_id=None,
            metadata={"model": "test-model"},
        )

    @pytest.mark.asyncio
    async def test_save_and_load_session(self, store, sample_session):
        """Test that a session can be saved and loaded."""
        await store.save(sample_session)
        loaded = await store.load("test-session-123")

        assert loaded is not None
        assert loaded.id == sample_session.id
        assert loaded.state == sample_session.state
        assert loaded.messages == sample_session.messages

    @pytest.mark.asyncio
    async def test_load_nonexistent_session(self, store):
        """Test that loading a nonexistent session returns None."""
        result = await store.load("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_session(self, store, sample_session):
        """Test that a session can be deleted."""
        await store.save(sample_session)
        await store.delete("test-session-123")

        loaded = await store.load("test-session-123")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, store, sample_session):
        """Test that sessions can be listed."""
        await store.save(sample_session)

        sessions = await store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == "test-session-123"

    @pytest.mark.asyncio
    async def test_list_empty(self, store):
        """Test that listing empty store returns empty list."""
        sessions = await store.list_sessions()
        assert sessions == []


class TestSessionSurvivesRestart:
    """Tests verifying sessions persist across process restarts."""

    @pytest.fixture
    def storage_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.mark.asyncio
    async def test_session_persists_after_restart(self, storage_dir):
        """Test that a session stored in one process can be loaded in another."""
        # First "process": create and save a session
        store1 = ACPFileSessionStore(storage_dir=storage_dir)
        session = ACPSessionRecord(
            id="persistent-session",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={"key": "value"},
            messages=[],
            metadata={"test": "data"},
        )
        await store1.save(session)

        # Second "process": create new store instance and load
        store2 = ACPFileSessionStore(storage_dir=storage_dir)
        loaded = await store2.load("persistent-session")

        assert loaded is not None
        assert loaded.id == "persistent-session"
        assert loaded.state == {"key": "value"}
        assert loaded.metadata == {"test": "data"}

    @pytest.mark.asyncio
    async def test_multiple_sessions_persist(self, storage_dir):
        """Test that multiple sessions persist across restarts."""
        # Save multiple sessions
        store1 = ACPFileSessionStore(storage_dir=storage_dir)
        for i in range(3):
            session = ACPSessionRecord(
                id=f"session-{i}",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                state={"index": i},
                messages=[],
            )
            await store1.save(session)

        # Load in new store
        store2 = ACPFileSessionStore(storage_dir=storage_dir)
        sessions = await store2.list_sessions()

        assert len(sessions) == 3
        session_ids = {s.id for s in sessions}
        assert session_ids == {"session-0", "session-1", "session-2"}


class TestMultipleAgentIsolation:
    """Tests for multiple ACP agent definitions isolation."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a session store for testing."""
        return ACPFileSessionStore(storage_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_sessions_isolated_by_id(self, store):
        """Test that different session IDs remain isolated."""
        session1 = ACPSessionRecord(
            id="agent1-session",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={"agent": "one"},
            messages=[],
        )
        session2 = ACPSessionRecord(
            id="agent2-session",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={"agent": "two"},
            messages=[],
        )

        await store.save(session1)
        await store.save(session2)

        loaded1 = await store.load("agent1-session")
        loaded2 = await store.load("agent2-session")

        assert loaded1.state["agent"] == "one"
        assert loaded2.state["agent"] == "two"

    @pytest.mark.asyncio
    async def test_delete_one_session_keeps_others(self, store):
        """Test that deleting one session doesn't affect others."""
        session1 = ACPSessionRecord(
            id="session-1",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={},
            messages=[],
        )
        session2 = ACPSessionRecord(
            id="session-2",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={},
            messages=[],
        )

        await store.save(session1)
        await store.save(session2)
        await store.delete("session-1")

        assert await store.load("session-1") is None
        assert await store.load("session-2") is not None


class TestDownstreamConsumerContract:
    """Tests verifying contract methods consumed by ACP-03, ACP-08, ACP-09, ACP-10."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a session store for testing."""
        return ACPFileSessionStore(storage_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_save_accepts_session_record(self, store):
        """Test that save accepts ACPSessionRecord (ACP-03 requirement)."""
        session = ACPSessionRecord(
            id="test-save",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={},
            messages=[],
        )
        # Should not raise
        await store.save(session)

    @pytest.mark.asyncio
    async def test_load_returns_optional_record(self, store):
        """Test that load returns Optional[ACPSessionRecord] (ACP-08 requirement)."""
        result = await store.load("nonexistent")
        assert result is None or isinstance(result, ACPSessionRecord)

    @pytest.mark.asyncio
    async def test_delete_removes_session(self, store):
        """Test that delete removes session (ACP-09 requirement)."""
        session = ACPSessionRecord(
            id="to-delete",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={},
            messages=[],
        )
        await store.save(session)
        await store.delete("to-delete")
        assert await store.load("to-delete") is None

    @pytest.mark.asyncio
    async def test_list_returns_record_list(self, store):
        """Test that list_sessions returns list[ACPSessionRecord] (ACP-10 requirement)."""
        sessions = await store.list_sessions()
        assert isinstance(sessions, list)
        for s in sessions:
            assert isinstance(s, ACPSessionRecord)


class TestSessionMetadata:
    """Tests for session metadata and capability snapshot storage."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a session store for testing."""
        return ACPFileSessionStore(storage_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_store_nanobot_session_key(self, store):
        """Test that nanobot session key can be stored in metadata."""
        session = ACPSessionRecord(
            id="acp-session-1",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={},
            messages=[],
            metadata={"nanobot_session_key": "telegram:12345"},
        )
        await store.save(session)

        loaded = await store.load("acp-session-1")
        assert loaded.metadata["nanobot_session_key"] == "telegram:12345"

    @pytest.mark.asyncio
    async def test_store_acp_agent_id(self, store):
        """Test that ACP agent ID can be stored in metadata."""
        session = ACPSessionRecord(
            id="acp-session-2",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={},
            messages=[],
            metadata={"acp_agent_id": "opencode"},
        )
        await store.save(session)

        loaded = await store.load("acp-session-2")
        assert loaded.metadata["acp_agent_id"] == "opencode"

    @pytest.mark.asyncio
    async def test_store_cwd(self, store):
        """Test that working directory can be stored in metadata."""
        session = ACPSessionRecord(
            id="acp-session-3",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={},
            messages=[],
            metadata={"cwd": "/workspace/project"},
        )
        await store.save(session)

        loaded = await store.load("acp-session-3")
        assert loaded.metadata["cwd"] == "/workspace/project"

    @pytest.mark.asyncio
    async def test_store_capability_snapshot(self, store):
        """Test that capability snapshot can be stored in metadata."""
        session = ACPSessionRecord(
            id="acp-session-4",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            state={},
            messages=[],
            metadata={
                "capabilities": ["filesystem", "terminal", "webfetch"],
                "capability_config": {"filesystem": {"allowed_paths": ["/workspace"]}},
            },
        )
        await store.save(session)

        loaded = await store.load("acp-session-4")
        assert loaded.metadata["capabilities"] == ["filesystem", "terminal", "webfetch"]
        assert loaded.metadata["capability_config"]["filesystem"]["allowed_paths"] == ["/workspace"]


class TestACPSessionBindingStore:
    """Tests for ACPSessionBindingStore - nanobot-to-ACP session bindings."""

    @pytest.fixture
    def binding_store(self, tmp_path):
        """Create a binding store for testing."""
        return ACPSessionBindingStore(storage_dir=tmp_path)

    @pytest.fixture
    def sample_binding(self):
        """Create a sample session binding."""
        return ACPSessionBinding(
            nanobot_session_key="telegram:12345",
            acp_agent_id="opencode",
            acp_session_id="acp-session-abc",
            cwd="/workspace/project",
            metadata={"mode": "agent", "config": {"model": "claude"}},
            capabilities=["filesystem", "terminal"],
        )

    def test_binding_creation(self, sample_binding):
        """Test that a binding can be created with all fields."""
        assert sample_binding.nanobot_session_key == "telegram:12345"
        assert sample_binding.acp_agent_id == "opencode"
        assert sample_binding.acp_session_id == "acp-session-abc"
        assert sample_binding.cwd == "/workspace/project"
        assert sample_binding.metadata == {"mode": "agent", "config": {"model": "claude"}}
        assert sample_binding.capabilities == ["filesystem", "terminal"]

    def test_binding_defaults(self, tmp_path):
        """Test that a binding has proper defaults for optional fields."""
        binding = ACPSessionBinding(
            nanobot_session_key="discord:67890",
            acp_agent_id="claude-code",
            acp_session_id="acp-session-def",
        )
        assert binding.cwd is None
        assert binding.metadata == {}
        assert binding.capabilities == []

    def test_binding_serialization(self, sample_binding):
        """Test that bindings can be serialized and deserialized."""
        data = sample_binding.to_dict()

        assert data["nanobot_session_key"] == "telegram:12345"
        assert data["acp_agent_id"] == "opencode"
        assert data["acp_session_id"] == "acp-session-abc"
        assert data["cwd"] == "/workspace/project"
        assert data["metadata"] == {"mode": "agent", "config": {"model": "claude"}}
        assert data["capabilities"] == ["filesystem", "terminal"]

        # Deserialize
        restored = ACPSessionBinding.from_dict(data)
        assert restored.nanobot_session_key == sample_binding.nanobot_session_key
        assert restored.acp_agent_id == sample_binding.acp_agent_id
        assert restored.acp_session_id == sample_binding.acp_session_id
        assert restored.cwd == sample_binding.cwd
        assert restored.metadata == sample_binding.metadata
        assert restored.capabilities == sample_binding.capabilities

    def test_save_and_load_binding(self, binding_store, sample_binding):
        """Test that a binding can be saved and loaded."""
        binding_store.save_binding(sample_binding)

        loaded = binding_store.load_binding("telegram:12345")
        assert loaded is not None
        assert loaded.nanobot_session_key == "telegram:12345"
        assert loaded.acp_agent_id == "opencode"
        assert loaded.acp_session_id == "acp-session-abc"

    def test_load_nonexistent_binding(self, binding_store):
        """Test that loading a nonexistent binding returns None."""
        result = binding_store.load_binding("nonexistent:key")
        assert result is None

    def test_delete_binding(self, binding_store, sample_binding):
        """Test that a binding can be deleted."""
        binding_store.save_binding(sample_binding)
        binding_store.delete_binding("telegram:12345")

        loaded = binding_store.load_binding("telegram:12345")
        assert loaded is None

    def test_list_bindings(self, binding_store):
        """Test that bindings can be listed."""
        for i in range(3):
            binding = ACPSessionBinding(
                nanobot_session_key=f"channel:{i}",
                acp_agent_id="opencode",
                acp_session_id=f"acp-session-{i}",
            )
            binding_store.save_binding(binding)

        bindings = binding_store.list_bindings()
        assert len(bindings) == 3
        keys = {b.nanobot_session_key for b in bindings}
        assert keys == {"channel:0", "channel:1", "channel:2"}

    def test_bindings_survive_restart(self, tmp_path):
        """Test that bindings persist across store restarts (process restart simulation)."""
        # First "process": create and save bindings
        store1 = ACPSessionBindingStore(storage_dir=tmp_path)
        binding = ACPSessionBinding(
            nanobot_session_key="telegram:restart-test",
            acp_agent_id="opencode",
            acp_session_id="persistent-acp-session",
            cwd="/workspace/persistent",
            metadata={"survived": True},
            capabilities=["filesystem"],
        )
        store1.save_binding(binding)

        # Second "process": create new store instance and load
        store2 = ACPSessionBindingStore(storage_dir=tmp_path)
        loaded = store2.load_binding("telegram:restart-test")

        assert loaded is not None
        assert loaded.acp_session_id == "persistent-acp-session"
        assert loaded.cwd == "/workspace/persistent"
        assert loaded.metadata["survived"] is True
        assert loaded.capabilities == ["filesystem"]

    def test_multiple_bindings_isolated(self, binding_store):
        """Test that different nanobot sessions have isolated bindings."""
        binding1 = ACPSessionBinding(
            nanobot_session_key="telegram:user1",
            acp_agent_id="opencode",
            acp_session_id="acp-session-1",
        )
        binding2 = ACPSessionBinding(
            nanobot_session_key="telegram:user2",
            acp_agent_id="claude-code",
            acp_session_id="acp-session-2",
        )

        binding_store.save_binding(binding1)
        binding_store.save_binding(binding2)

        loaded1 = binding_store.load_binding("telegram:user1")
        loaded2 = binding_store.load_binding("telegram:user2")

        assert loaded1.acp_agent_id == "opencode"
        assert loaded2.acp_agent_id == "claude-code"
        assert loaded1.acp_session_id == "acp-session-1"
        assert loaded2.acp_session_id == "acp-session-2"

    def test_update_existing_binding(self, binding_store, sample_binding):
        """Test that saving a binding with the same key updates it."""
        binding_store.save_binding(sample_binding)

        # Update with new ACP session
        updated_binding = ACPSessionBinding(
            nanobot_session_key="telegram:12345",  # Same key
            acp_agent_id="opencode",
            acp_session_id="acp-session-new",  # New session ID
            cwd="/new/workspace",
        )
        binding_store.save_binding(updated_binding)

        loaded = binding_store.load_binding("telegram:12345")
        assert loaded.acp_session_id == "acp-session-new"
        assert loaded.cwd == "/new/workspace"
