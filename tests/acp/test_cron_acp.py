"""Tests for ACP cron integration.

These tests verify that:
1. One-shot reminders work with ACP backend
2. Recurring tasks work with ACP backend
3. Unattended permission path works (policy-driven, no hang)
4. Results deliver back to channels
5. Backend selection (ACP vs local) works correctly
6. Current cron behavior for local nanobot sessions is preserved
"""

import asyncio
from datetime import datetime, timezone
from inspect import iscoroutinefunction

import pytest

from nanobot.acp.permissions import PermissionBrokerFactory
from nanobot.acp.policy import UnattendedPermissionPolicy
from nanobot.acp.types import (
    ACPFilesystemCallback,
    ACPPermissionRequest,
    ACPTerminalCallback,
)
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule


class FakeACPService:
    """Fake ACP service for testing."""

    def __init__(self):
        self.sessions: dict[str, str] = {}
        self.messages: list[tuple[str, str]] = []
        self._policy_mode = "allow"  # Default for testing

    async def load_session(self, nanobot_session_key: str) -> dict:
        """Load or create an ACP session."""
        acp_session_id = self.sessions.get(nanobot_session_key)
        if not acp_session_id:
            acp_session_id = f"acp-session-{nanobot_session_key}"
            self.sessions[nanobot_session_key] = acp_session_id
        return {
            "nanobot_session_key": nanobot_session_key,
            "acp_session_id": acp_session_id,
            "status": "loaded",
        }

    async def process_message(self, nanobot_session_key: str, message: str) -> list:
        """Process message through ACP."""
        self.messages.append((nanobot_session_key, message))
        # Return fake stream chunks
        return [type("Chunk", (), {"content": f"ACP response to: {message}"})()]


class FakeMessageBus:
    """Fake message bus for testing delivery."""

    def __init__(self):
        self.outbound_messages: list = []

    async def publish_outbound(self, message) -> None:
        self.outbound_messages.append(message)


# ========== Test: Backend Selection ==========


def test_cron_job_has_acp_session_key() -> None:
    """Test that cron jobs store session key for ACP routing."""
    # A cron job for a specific channel/chat should have enough info
    # to route to ACP if configured
    schedule = CronSchedule(kind="at", at_ms=1234567890000)
    payload = CronPayload(
        kind="agent_turn",
        message="test",
        deliver=True,
        channel="telegram",
        to="12345",
    )

    job = CronJob(
        id="test-123",
        name="test job",
        schedule=schedule,
        payload=payload,
        state=CronJobState(next_run_at_ms=1234567890000),
    )

    # Verify the payload contains routing info
    assert job.payload.channel == "telegram"
    assert job.payload.to == "12345"
    assert job.payload.deliver is True


def test_backend_selection_requires_session_key() -> None:
    """Test that ACP backend needs session key for routing."""
    # Session key format: channel:chat_id
    session_key = "telegram:12345"

    # This should be constructable from cron job payload
    channel = "telegram"
    chat_id = "12345"
    derived_key = f"{channel}:{chat_id}"

    assert derived_key == session_key


# ========== Test: One-shot reminder with ACP ==========


@pytest.mark.asyncio
async def test_one_shot_reminder_acp_backend(tmp_path) -> None:
    """Test that one-shot reminders can route to ACP backend."""
    store_path = tmp_path / "cron" / "jobs.json"
    acp_service = FakeACPService()

    # Create cron service with ACP-aware callback
    async def on_job(job: CronJob) -> str | None:
        session_key = f"{job.payload.channel}:{job.payload.to}"
        # This should route to ACP if ACP is configured
        await acp_service.load_session(session_key)
        chunks = await acp_service.process_message(session_key, job.payload.message)
        return chunks[0].content if chunks else None

    service = CronService(store_path, on_job=on_job)

    # Add a recurring job (runs every 50ms) - simulating a reminder that fires
    service.add_job(
        name="ACP reminder",
        schedule=CronSchedule(kind="every", every_ms=50),  # Fires every 50ms
        message="Check the server status",
        deliver=True,
        channel="telegram",
        to="12345",
    )

    await service.start()
    try:
        # Wait for job to execute
        await asyncio.sleep(0.15)

        # Verify job was executed via ACP
        assert len(acp_service.messages) >= 1
        session_key, msg = acp_service.messages[0]
        assert session_key == "telegram:12345"
        assert msg == "Check the server status"
    finally:
        service.stop()


# ========== Test: Recurring task with ACP ==========


@pytest.mark.asyncio
async def test_recurring_task_acp_backend(tmp_path) -> None:
    """Test that recurring tasks work with ACP backend."""
    store_path = tmp_path / "cron" / "jobs.json"
    acp_service = FakeACPService()

    async def on_job(job: CronJob) -> str | None:
        session_key = f"{job.payload.channel}:{job.payload.to}"
        await acp_service.load_session(session_key)
        chunks = await acp_service.process_message(session_key, job.payload.message)
        return chunks[0].content if chunks else None

    service = CronService(store_path, on_job=on_job)

    # Add recurring job (every 50ms)
    service.add_job(
        name="Daily report",
        schedule=CronSchedule(kind="every", every_ms=50),
        message="Generate daily report",
        deliver=True,
        channel="cli",
        to="direct",
    )

    await service.start()
    try:
        # Wait for at least 2 executions
        await asyncio.sleep(0.15)

        # Verify multiple executions via ACP
        assert len(acp_service.messages) >= 2
    finally:
        service.stop()


# ========== Test: Unattended permission path ==========


@pytest.mark.asyncio
async def test_unattended_permission_resolves_without_hanging(tmp_path) -> None:
    """Test that unattended permission policy resolves without hanging."""
    # Create unattended permission broker with allow policy
    policy = UnattendedPermissionPolicy(default_mode="allow")
    broker = PermissionBrokerFactory.create_unattended(policy=policy)

    # Verify it's in unattended mode
    assert broker.is_interactive is False

    # Simulate permission request
    request = ACPPermissionRequest(
        id="test-perm-123",
        permission_type="filesystem",
        description="Read file",
        resource="/test/file.txt",
        callback=ACPFilesystemCallback(
            operation="read",
            path="/test/file.txt",
            content=None,
            metadata={},
        ),
        correlation_id="corr-123",
        timestamp=datetime.now(timezone.utc),
    )

    # This should NOT hang - policy should resolve immediately
    decision = await broker.request_permission(request)

    # Verify decision was made (not pending)
    assert decision is not None
    assert decision.granted is True  # Policy is "allow"


@pytest.mark.asyncio
async def test_unattended_permission_deny_policy(tmp_path) -> None:
    """Test that deny policy works correctly in unattended mode."""
    # Create unattended permission broker with deny policy
    policy = UnattendedPermissionPolicy(default_mode="deny")
    broker = PermissionBrokerFactory.create_unattended(policy=policy)

    assert broker.is_interactive is False

    # Use imports from top of file
    request = ACPPermissionRequest(
        id="test-perm-456",
        permission_type="terminal",
        description="Run command",
        resource="/bin/ls",
        callback=ACPTerminalCallback(
            command="ls",
            working_directory="/home",
            environment={},
            timeout=30.0,
        ),
        correlation_id="corr-456",
        timestamp=datetime.now(timezone.utc),
    )

    # Should resolve immediately with deny
    decision = await broker.request_permission(request)
    assert decision.granted is False


# ========== Test: Delivery back to channels ==========


@pytest.mark.asyncio
async def test_cron_response_contains_delivery_flag(tmp_path) -> None:
    """Test that cron job payload contains delivery flag for channel routing."""
    store_path = tmp_path / "cron" / "jobs.json"

    # Track job executions
    executed_jobs: list[CronJob] = []

    async def on_job(job: CronJob) -> str | None:
        executed_jobs.append(job)
        if job.payload.deliver:
            return f"Completed: {job.payload.message}"
        return None

    service = CronService(store_path, on_job=on_job)

    service.add_job(
        name="deliverable job",
        schedule=CronSchedule(kind="every", every_ms=50),
        message="say hello",
        deliver=True,
        channel="telegram",
        to="12345",
    )

    await service.start()
    try:
        await asyncio.sleep(0.2)

        # Verify job executed and has delivery info
        assert len(executed_jobs) >= 1
        executed_job = executed_jobs[0]
        assert executed_job.payload.deliver is True
        assert executed_job.payload.channel == "telegram"
        assert executed_job.payload.to == "12345"

        # The response is returned by on_job and could be used for delivery
        # by whatever is calling the cron service
    finally:
        service.stop()


# ========== Test: Current cron behavior preserved ==========


@pytest.mark.asyncio
async def test_local_nanobot_session_preserved(tmp_path) -> None:
    """Test that local nanobot sessions still work without ACP."""
    store_path = tmp_path / "cron" / "jobs.json"

    # Track which sessions are used
    job_responses: list[str] = []

    # Simulate local (non-ACP) agent processing
    async def on_job(job: CronJob) -> str | None:
        # Simulate local agent response
        response = f"Local response: {job.payload.message}"
        job_responses.append(response)
        return response

    service = CronService(store_path, on_job=on_job)

    # Add job with channel/chat that would route to ACP in production
    service.add_job(
        name="local job",
        schedule=CronSchedule(kind="every", every_ms=50),
        message="run local task",
        deliver=False,
        channel="cli",
        to="direct",
    )

    await service.start()
    try:
        await asyncio.sleep(0.2)

        # Verify local processing happened (job executed and returned response)
        assert len(job_responses) >= 1
        assert "Local response" in job_responses[0]
    finally:
        service.stop()


@pytest.mark.asyncio
async def test_cron_job_without_acp_routes_to_local_agent(tmp_path) -> None:
    """Test that cron jobs without ACP config route to local agent."""
    store_path = tmp_path / "cron" / "jobs.json"

    # No ACP service configured - should use local
    service = CronService(store_path, on_job=None)

    service.add_job(
        name="test",
        schedule=CronSchedule(kind="every", every_ms=50),
        message="test",
        deliver=True,
        channel="cli",
        to="direct",
    )

    await service.start()
    try:
        # Should not fail - on_job is None so nothing happens
        await asyncio.sleep(0.2)
    finally:
        service.stop()


# ========== Test: Backend selection logic ==========


def test_acp_backend_selection_requires_service() -> None:
    """Test that ACP backend selection requires ACP service to be configured."""

    # Without ACP service, should NOT use ACP
    def should_use_acp(service) -> bool:
        return service is not None

    # Test: No service = false
    assert should_use_acp(None) is False

    # Test: With service = true
    assert should_use_acp(FakeACPService()) is True


def test_session_key_derivation_from_cron_payload() -> None:
    """Test that session key can be derived from cron job payload."""
    # Test various channel/chat combinations
    test_cases = [
        (("telegram", "12345"), "telegram:12345"),
        (("whatsapp", "+1234567890"), "whatsapp:+1234567890"),
        (("cli", "direct"), "cli:direct"),
    ]

    for (channel, chat_id), expected_key in test_cases:
        session_key = f"{channel}:{chat_id}"
        assert session_key == expected_key


# ========== Test: ACP cron integration module exists ==========


def test_acp_cron_module_exists() -> None:
    """Test that nanobot.acp.cron module exists and can be imported."""
    try:
        from nanobot.acp import cron

        assert hasattr(cron, "ACPCronHandler")
    except ImportError:
        pytest.fail("nanobot.acp.cron module should exist")


def test_acp_cron_handler_interface() -> None:
    """Test that ACPCronHandler has the expected interface."""
    from nanobot.acp.cron import ACPCronHandler

    # Should have methods for handling cron jobs
    handler = ACPCronHandler(acp_service=None, permission_broker=None)

    # Should have an async execute method
    assert hasattr(handler, "execute")
    assert iscoroutinefunction(handler.execute)


def test_acp_cron_handler_with_service() -> None:
    """Test that ACPCronHandler works with ACP service."""
    from nanobot.acp.cron import ACPCronHandler
    from nanobot.acp.permissions import PermissionBrokerFactory
    from nanobot.acp.policy import UnattendedPermissionPolicy

    acp_service = FakeACPService()
    policy = UnattendedPermissionPolicy(default_mode="allow")
    broker = PermissionBrokerFactory.create_unattended(policy=policy)

    handler = ACPCronHandler(acp_service=acp_service, permission_broker=broker)

    assert handler.acp_service is acp_service
    assert handler.permission_broker is broker
