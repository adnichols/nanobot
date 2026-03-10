"""ACP Terminal Manager implementation.

This module provides managed asyncio subprocess-based terminal lifecycle support
for ACP sessions. It tracks terminal state per terminal ID, isolates terminals
per ACP session, and provides operations for create, output, wait_for_exit,
kill, and release.

Key design decisions:
- Uses managed asyncio subprocesses with explicit terminal state and lifecycle
- Does NOT reuse ExecTool directly - uses asyncio subprocess directly
- Keeps terminal management separate from user-visible rendering
- Integrates through register_terminal_callback() hook from ACP-03
- PTY support is a scoped escalation, not the default assumption
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Awaitable, Callable, Optional

from nanobot.acp.types import ACPPermissionDecision, ACPTerminalCallback


class ACPTerminalState(Enum):
    """Terminal lifecycle states."""

    CREATED = auto()  # Terminal created, process not yet started
    RUNNING = auto()  # Process is running
    COMPLETED = auto()  # Process completed normally
    KILLED = auto()  # Process was killed
    RELEASED = auto()  # Resources released


@dataclass
class ACPTerminal:
    """Represents a single terminal instance with state tracking."""

    terminal_id: str
    command: list[str]
    working_directory: Optional[str] = None
    environment: dict[str, str] = field(default_factory=dict)
    state: ACPTerminalState = ACPTerminalState.CREATED
    exit_code: Optional[int] = None
    _process: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    _output_buffer: list[str] = field(default_factory=list, repr=False)

    @property
    def output(self) -> str:
        """Get the combined output from stdout and stderr."""
        return "".join(self._output_buffer)


class ACPInvalidTerminalError(Exception):
    """Error raised when accessing an invalid or released terminal."""

    def __init__(self, terminal_id: str, reason: Optional[str] = None):
        self.terminal_id = terminal_id
        self.reason = reason
        msg = f"Invalid terminal: {terminal_id}"
        if reason:
            msg += f" - {reason}"
        super().__init__(msg)


class ACPTerminalManager:
    """Manages terminal lifecycle for ACP sessions.

    This manager provides:
    - Terminal creation with asyncio subprocess
    - Output retrieval from terminal stdout/stderr
    - Wait for process exit with optional timeout
    - Process kill for runaway commands
    - Resource release and cleanup

    Terminal state is tracked by terminal_id and isolated per ACP session.
    """

    def __init__(
        self,
        callback_registry: Optional[Any] = None,
    ):
        """Initialize the terminal manager.

        Args:
            callback_registry: Optional callback registry for permission handling.
        """
        self._terminals: dict[str, ACPTerminal] = {}
        self._callback_registry = callback_registry
        self._permission_handler: Optional[
            Callable[[ACPTerminalCallback], Awaitable[ACPPermissionDecision]]
        ] = None
        self._internal_handler: bool = True  # Track if we use internal handler

        # Register with callback registry if provided
        # Only register our internal handler if no handler is already registered
        if callback_registry is not None:
            existing_handler = getattr(callback_registry, "_terminal_handler", None)
            if existing_handler is None:
                callback_registry.register_terminal_callback(self._handle_permission)
            self._internal_handler = False

    async def _handle_permission(self, callback: ACPTerminalCallback) -> ACPPermissionDecision:
        """Handle terminal permission request."""
        # Default: allow all terminal operations
        # In production, this would be connected to user permission prompts
        return ACPPermissionDecision(
            request_id=uuid.uuid4().hex,
            granted=True,
            reason="Allowed by default",
        )

    def _get_terminal_handler(
        self,
    ) -> Optional[Callable[[ACPTerminalCallback], Awaitable[ACPPermissionDecision]]]:
        """Get the terminal permission handler from registry or internal."""
        if self._callback_registry is not None:
            # Try to get handler from callback registry
            # The registry stores the handler in _terminal_handler
            handler = getattr(self._callback_registry, "_terminal_handler", None)
            if handler is not None:
                return handler

        # Use internal handler only if no external registry
        if self._internal_handler:
            return self._handle_permission

        return None

    async def create(
        self,
        command: list[str],
        working_directory: Optional[str] = None,
        environment: Optional[dict[str, str]] = None,
    ) -> str:
        """Create a new terminal with the given command.

        Args:
            command: Command and arguments to execute.
            working_directory: Optional working directory.
            environment: Optional environment variables.

        Returns:
            Terminal ID for the created terminal.

        Raises:
            PermissionError: If terminal permission is denied.
            ValueError: If command is empty.
        """
        if not command:
            raise ValueError("Command cannot be empty")

        # Request permission if handler is registered
        handler = self._get_terminal_handler()
        if handler is not None:
            callback = ACPTerminalCallback(
                command=" ".join(command),
                working_directory=working_directory,
                environment=environment or {},
            )
            decision = await handler(callback)
            if not decision.granted:
                raise PermissionError(f"Terminal permission denied: {decision.reason}")

        # Generate terminal ID
        terminal_id = f"term-{uuid.uuid4().hex[:12]}"

        # Create terminal record
        terminal = ACPTerminal(
            terminal_id=terminal_id,
            command=command,
            working_directory=working_directory,
            environment=environment or {},
            state=ACPTerminalState.CREATED,
        )

        self._terminals[terminal_id] = terminal

        # Start the subprocess
        await self._start_process(terminal_id)

        return terminal_id

    async def _start_process(self, terminal_id: str) -> None:
        """Start the subprocess for a terminal.

        Args:
            terminal_id: ID of the terminal to start.

        Raises:
            ACPInvalidTerminalError: If terminal does not exist.
        """
        terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise ACPInvalidTerminalError(terminal_id, "Terminal not found")

        try:
            # Create subprocess with pipes for stdout/stderr
            process = await asyncio.create_subprocess_exec(
                *terminal.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=terminal.working_directory,
                env=terminal.environment,
            )

            terminal._process = process
            terminal.state = ACPTerminalState.RUNNING

            # Start background task to read output
            asyncio.create_task(self._read_output(terminal_id))

        except FileNotFoundError:
            # Command not found - mark as completed with error
            # Terminal is still valid, caller can check exit code via wait_for_exit
            terminal.state = ACPTerminalState.COMPLETED
            terminal.exit_code = 127
            # Don't raise here - let the caller use wait_for_exit to get the exit code
        except Exception:
            # Other errors during start - mark as completed with error
            terminal.state = ACPTerminalState.COMPLETED
            terminal.exit_code = 1
            # Don't raise here - let the caller use wait_for_exit to get the exit code

    async def _read_output(self, terminal_id: str) -> None:
        """Read output from the terminal process in the background.

        Args:
            terminal_id: ID of the terminal to read from.
        """
        terminal = self._terminals.get(terminal_id)
        if terminal is None or terminal._process is None:
            return

        process = terminal._process

        try:
            # Read stdout
            if process.stdout:
                stdout_data = await process.stdout.read()
                if stdout_data:
                    terminal._output_buffer.append(stdout_data.decode("utf-8", errors="replace"))

            # Read stderr
            if process.stderr:
                stderr_data = await process.stderr.read()
                if stderr_data:
                    terminal._output_buffer.append(stderr_data.decode("utf-8", errors="replace"))

        except Exception:
            # Ignore read errors - they'll be handled in wait_for_exit
            pass

    async def output(self, terminal_id: str) -> str:
        """Get output from a terminal.

        Args:
            terminal_id: ID of the terminal.

        Returns:
            Combined stdout and stderr output.

        Raises:
            ACPInvalidTerminalError: If terminal is invalid or released.
        """
        terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise ACPInvalidTerminalError(terminal_id, "Terminal does not exist")

        if terminal.state == ACPTerminalState.RELEASED:
            raise ACPInvalidTerminalError(terminal_id, "Terminal was released")

        # Read any remaining output
        if terminal._process and terminal._process.returncode is not None:
            await self._read_output(terminal_id)

        return "".join(terminal._output_buffer)

    async def wait_for_exit(self, terminal_id: str, timeout: Optional[float] = None) -> int:
        """Wait for a terminal process to exit.

        Args:
            terminal_id: ID of the terminal.
            timeout: Optional timeout in seconds.

        Returns:
            Exit code of the process.

        Raises:
            ACPInvalidTerminalError: If terminal is invalid or released.
            asyncio.TimeoutError: If timeout is reached before exit.
        """
        terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise ACPInvalidTerminalError(terminal_id, "Terminal does not exist")

        if terminal.state == ACPTerminalState.RELEASED:
            raise ACPInvalidTerminalError(terminal_id, "Terminal was released")

        if terminal.state == ACPTerminalState.COMPLETED:
            return terminal.exit_code or 0

        if terminal._process is None:
            raise ACPInvalidTerminalError(terminal_id, "Process not started")

        # Wait for process to exit
        try:
            if timeout is not None:
                exit_code = await asyncio.wait_for(terminal._process.wait(), timeout=timeout)
            else:
                exit_code = await terminal._process.wait()

            terminal.exit_code = exit_code

            # Read any remaining output
            await self._read_output(terminal_id)

            # Update state based on how process exited
            if terminal.state != ACPTerminalState.KILLED:
                terminal.state = ACPTerminalState.COMPLETED

            return exit_code

        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(
                f"Terminal {terminal_id} did not exit within {timeout} seconds"
            )

    async def kill(self, terminal_id: str) -> None:
        """Kill a running terminal process.

        Args:
            terminal_id: ID of the terminal to kill.

        Raises:
            ACPInvalidTerminalError: If terminal is invalid or already released.
        """
        terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise ACPInvalidTerminalError(terminal_id, "Terminal does not exist")

        if terminal.state == ACPTerminalState.RELEASED:
            raise ACPInvalidTerminalError(terminal_id, "Terminal was released")

        if terminal.state == ACPTerminalState.COMPLETED:
            # Already completed - state remains COMPLETED
            return

        if terminal._process and terminal._process.returncode is None:
            try:
                terminal._process.terminate()
                try:
                    await asyncio.wait_for(terminal._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    terminal._process.kill()
                    await terminal._process.wait()
            except Exception:
                # Process may have already exited
                pass

        terminal.state = ACPTerminalState.KILLED
        terminal.exit_code = -9  # Signal that process was killed

    async def release(self, terminal_id: str) -> None:
        """Release terminal resources.

        Args:
            terminal_id: ID of the terminal to release.

        Raises:
            ACPInvalidTerminalError: If terminal is invalid.
        """
        terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise ACPInvalidTerminalError(terminal_id, "Terminal does not exist")

        # Clean up process if still running
        if terminal._process and terminal._process.returncode is None:
            try:
                terminal._process.terminate()
                try:
                    await asyncio.wait_for(terminal._process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    terminal._process.kill()
                    await terminal._process.wait()
            except Exception:
                pass

        # Clear resources
        terminal._process = None
        terminal._output_buffer.clear()
        terminal.state = ACPTerminalState.RELEASED

    def get_terminal_state(self, terminal_id: str) -> ACPTerminalState:
        """Get the current state of a terminal.

        Args:
            terminal_id: ID of the terminal.

        Returns:
            Current terminal state.

        Raises:
            ACPInvalidTerminalError: If terminal is invalid or released.
        """
        terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise ACPInvalidTerminalError(terminal_id, "Terminal does not exist")

        return terminal.state
