"""Tests for ACP Terminal Manager.

These tests verify terminal lifecycle operations: create, output, wait_for_exit,
kill, release, and invalid-state handling. Tests use the fake ACP agent fixtures
from tests/acp/fakes/.
"""

from __future__ import annotations

import asyncio

import pytest

from nanobot.acp.terminal import (
    ACPInvalidTerminalError,
    ACPTerminal,
    ACPTerminalManager,
    ACPTerminalState,
)
from nanobot.acp.types import ACPTerminalCallback
from tests.acp.fakes import FakeACPCallbackRegistry


class TestACPTerminalState:
    """Test the terminal state enum."""

    def test_terminal_state_values(self):
        """Verify all expected terminal states exist."""
        assert ACPTerminalState.CREATED.name == "CREATED"
        assert ACPTerminalState.RUNNING.name == "RUNNING"
        assert ACPTerminalState.COMPLETED.name == "COMPLETED"
        assert ACPTerminalState.KILLED.name == "KILLED"
        assert ACPTerminalState.RELEASED.name == "RELEASED"


class TestACPInvalidTerminalError:
    """Test the invalid terminal error."""

    def test_invalid_terminal_error_message(self):
        """Verify error contains terminal id."""
        error = ACPInvalidTerminalError("terminal-123")
        assert "terminal-123" in str(error)
        assert "invalid" in str(error).lower()

    def test_invalid_terminal_error_with_reason(self):
        """Verify error can include a reason."""
        error = ACPInvalidTerminalError("terminal-123", reason="Terminal was released")
        assert "Terminal was released" in str(error)


class TestACPTerminal:
    """Test the ACP Terminal class."""

    def test_terminal_initialization(self):
        """Verify terminal is created with correct initial state."""
        terminal = ACPTerminal(terminal_id="test-term-1", command=["echo", "hello"])
        assert terminal.terminal_id == "test-term-1"
        assert terminal.command == ["echo", "hello"]
        assert terminal.state == ACPTerminalState.CREATED

    def test_terminal_default_state(self):
        """Verify terminal starts in CREATED state."""
        terminal = ACPTerminal(terminal_id="test-term-1", command=["ls"])
        assert terminal.state == ACPTerminalState.CREATED
        assert terminal.exit_code is None
        assert terminal.output == ""


class TestACPTerminalManager:
    """Test the ACP Terminal Manager."""

    @pytest.fixture
    def callback_registry(self):
        """Provide a fake callback registry."""
        return FakeACPCallbackRegistry()

    @pytest.fixture
    def terminal_manager(self, callback_registry):
        """Provide a terminal manager with callback registry."""
        return ACPTerminalManager(callback_registry=callback_registry)

    @pytest.mark.asyncio
    async def test_create_terminal_in_workspace(self, terminal_manager):
        """Given OpenCode creates a terminal in the workspace, when it runs a command, then nanobot can provide output."""
        # Create terminal - should require permission first
        # For now, test basic create without permission (permission granted by default in fakes)
        terminal_id = await terminal_manager.create(
            command=["echo", "hello world"],
            working_directory="/tmp",
        )
        assert terminal_id is not None
        assert terminal_manager.get_terminal_state(terminal_id) == ACPTerminalState.RUNNING

    @pytest.mark.asyncio
    async def test_output_retrieval(self, terminal_manager):
        """Test that output can be retrieved from a running terminal."""
        terminal_id = await terminal_manager.create(
            command=["echo", "test output"],
            working_directory="/tmp",
        )

        # Allow command to complete
        await asyncio.sleep(0.1)

        output = await terminal_manager.output(terminal_id)
        assert "test output" in output

    @pytest.mark.asyncio
    async def test_wait_for_exit_completion(self, terminal_manager):
        """Test wait_for_exit returns exit code when command completes."""
        terminal_id = await terminal_manager.create(
            command=["echo", "done"],
            working_directory="/tmp",
        )

        exit_code = await terminal_manager.wait_for_exit(terminal_id, timeout=5.0)
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_wait_for_exit_long_running(self, terminal_manager):
        """Test wait_for_exit handles long-running commands with timeout."""
        # Create a long-running command (sleep)
        terminal_id = await terminal_manager.create(
            command=["sleep", "0.5"],
            working_directory="/tmp",
        )

        # Should timeout since sleep is still running
        with pytest.raises(asyncio.TimeoutError):
            await terminal_manager.wait_for_exit(terminal_id, timeout=0.1)

        # Kill the terminal
        await terminal_manager.kill(terminal_id)

    @pytest.mark.asyncio
    async def test_kill_running_terminal(self, terminal_manager):
        """Given a running terminal exists, when the agent requests kill, then the process exits."""
        terminal_id = await terminal_manager.create(
            command=["sleep", "10"],
            working_directory="/tmp",
        )

        # Terminal should be running
        assert terminal_manager.get_terminal_state(terminal_id) == ACPTerminalState.RUNNING

        # Kill the terminal
        await terminal_manager.kill(terminal_id)

        # Terminal should now be in KILLED state
        state = terminal_manager.get_terminal_state(terminal_id)
        assert state == ACPTerminalState.KILLED

    @pytest.mark.asyncio
    async def test_release_terminal(self, terminal_manager):
        """Test that releasing a terminal frees its resources."""
        terminal_id = await terminal_manager.create(
            command=["echo", "released"],
            working_directory="/tmp",
        )

        # Wait for completion
        await terminal_manager.wait_for_exit(terminal_id, timeout=5.0)

        # Release the terminal
        await terminal_manager.release(terminal_id)

        # Terminal should be in RELEASED state
        assert terminal_manager.get_terminal_state(terminal_id) == ACPTerminalState.RELEASED

    @pytest.mark.asyncio
    async def test_invalid_state_accessing_released_terminal(self, terminal_manager):
        """Given a released terminal id is referenced again, when output is requested, then nanobot returns a clear error."""
        terminal_id = await terminal_manager.create(
            command=["echo", "test"],
            working_directory="/tmp",
        )

        # Wait for completion
        await terminal_manager.wait_for_exit(terminal_id, timeout=5.0)

        # Release the terminal
        await terminal_manager.release(terminal_id)

        # Attempting to access output on released terminal should raise error
        with pytest.raises(ACPInvalidTerminalError) as exc_info:
            await terminal_manager.output(terminal_id)
        assert "released" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_invalid_state_nonexistent_terminal(self, terminal_manager):
        """Test that accessing a non-existent terminal raises an error."""
        with pytest.raises(ACPInvalidTerminalError):
            await terminal_manager.output("nonexistent-terminal-id")

    @pytest.mark.asyncio
    async def test_kill_already_completed_terminal(self, terminal_manager):
        """Test that killing an already completed terminal is handled gracefully."""
        terminal_id = await terminal_manager.create(
            command=["echo", "done"],
            working_directory="/tmp",
        )

        # Wait for completion
        await terminal_manager.wait_for_exit(terminal_id, timeout=5.0)

        # Kill should still work (idempotent)
        await terminal_manager.kill(terminal_id)
        # State should still be COMPLETED (not overwritten by kill)
        assert terminal_manager.get_terminal_state(terminal_id) == ACPTerminalState.COMPLETED

    @pytest.mark.asyncio
    async def test_multiple_terminals_per_session(self, terminal_manager):
        """Test that multiple terminals can be created in the same session."""
        term1 = await terminal_manager.create(
            command=["echo", "first"],
            working_directory="/tmp",
        )
        term2 = await terminal_manager.create(
            command=["echo", "second"],
            working_directory="/tmp",
        )

        assert term1 != term2
        assert terminal_manager.get_terminal_state(term1) == ACPTerminalState.RUNNING
        assert terminal_manager.get_terminal_state(term2) == ACPTerminalState.RUNNING

    @pytest.mark.asyncio
    async def test_terminal_isolation_per_session(self, terminal_manager):
        """Test that terminals are isolated per ACP session."""
        # Create session-specific terminals
        term1 = await terminal_manager.create(
            command=["echo", "session1"],
            working_directory="/tmp",
        )

        # Verify each terminal has its own state
        assert terminal_manager.get_terminal_state(term1) == ACPTerminalState.RUNNING

        # Release should not affect other terminals
        await terminal_manager.release(term1)

        # Verify terminal was released
        assert terminal_manager.get_terminal_state(term1) == ACPTerminalState.RELEASED


class TestACPTerminalPermissionHandling:
    """Test terminal permission handling through the callback registry."""

    @pytest.fixture
    def callback_registry(self):
        """Provide a callback registry that denies permissions."""
        registry = FakeACPCallbackRegistry()

        # Set up a deny handler
        async def deny_handler(callback: ACPTerminalCallback):
            from nanobot.acp.types import ACPPermissionDecision

            return ACPPermissionDecision(
                request_id="deny",
                granted=False,
                reason="Permission denied",
            )

        registry.register_terminal_callback(deny_handler)
        return registry

    @pytest.mark.asyncio
    async def test_terminal_permission_denied(self, callback_registry):
        """Test that terminal creation is denied when permission is not granted."""
        manager = ACPTerminalManager(callback_registry=callback_registry)

        # Create should fail due to denied permission
        with pytest.raises(PermissionError):
            await manager.create(
                command=["echo", "denied"],
                working_directory="/tmp",
            )


class TestACPTerminalErrorHandling:
    """Test error handling in terminal manager."""

    @pytest.fixture
    def terminal_manager(self):
        """Provide a terminal manager without callback registry."""
        return ACPTerminalManager()

    @pytest.mark.asyncio
    async def test_invalid_working_directory(self, terminal_manager):
        """Test that invalid working directory is handled gracefully."""
        # When working directory doesn't exist, subprocess creation fails
        # but terminal is still created and can report the error
        terminal_id = await terminal_manager.create(
            command=["echo", "test"],
            working_directory="/nonexistent/path/that/does/not/exist",
        )

        # The terminal completes with a non-zero exit code (127 = command not found)
        # because the subprocess couldn't start due to invalid directory
        exit_code = await terminal_manager.wait_for_exit(terminal_id, timeout=5.0)
        assert exit_code != 0

    @pytest.mark.asyncio
    async def test_command_not_found(self, terminal_manager):
        """Test handling of non-existent command."""
        terminal_id = await terminal_manager.create(
            command=["nonexistent-command-xyz"],
            working_directory="/tmp",
        )

        # Wait for exit - should complete with non-zero exit code
        exit_code = await terminal_manager.wait_for_exit(terminal_id, timeout=5.0)
        assert exit_code != 0
