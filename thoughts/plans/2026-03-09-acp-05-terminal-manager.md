# ACP-05 Terminal Manager

## Status

- ready

## Goal

- Implement ACP terminal lifecycle support as a managed subsystem.

## Product intent alignment

- Advances Outcome 1 by enabling external ACP agents to run commands through a real client-side terminal layer.
- Supports Principles 3 and 4.

## Dependencies

- `ACP-00`
- `ACP-01`
- integrates with callback registration from `ACP-03`

## File ownership

- `nanobot/acp/terminal.py`
- `tests/acp/test_terminal_manager.py`

## ACP interfaces consumed

- `ACPTerminalHandler` and registration hooks from `ACP-01` and `ACP-03`
- shared session and request types from `ACP-01`

## Acceptance criteria

- ACP `terminal/create`, `terminal/output`, `terminal/wait_for_exit`, `terminal/kill`, and `terminal/release` are implemented.
- Terminal state is tracked by terminal id and isolated per ACP session.
- Long-running command behavior and invalid-state handling are test-covered.

## BDD scenarios

- Given OpenCode creates a terminal in the workspace, when it runs a command, then nanobot can provide output and final exit status.
- Given a running terminal exists, when the agent requests kill, then the process exits and state updates correctly.
- Given a released terminal id is referenced again, when output is requested, then nanobot returns a clear invalid-terminal error.

## Progress

- [x] ACP05.1 Add failing terminal tests
- [x] ACP05.2 Implement terminal lifecycle state (terminal/create, output, wait_for_exit)
- [x] ACP05.3 Implement output and wait semantics
- [x] ACP05.4 Implement kill and release behavior (19 tests passing)

## Phase 1

### End state

- Managed ACP terminal support exists behind deterministic tests.

### Tests first

- Add failing tests for create, output, wait, kill, release, and invalid-state handling.

### Work

- Do not reuse `ExecTool` directly as the ACP terminal runtime.
- Keep terminal management separate from user-visible rendering.
- Start with a managed `asyncio` subprocess terminal layer that preserves per-terminal state and lifecycle semantics; only widen to PTY-backed behavior if contract tests or OpenCode behavior prove pipes are insufficient.

### Verify

- `uv run pytest tests/acp/test_terminal_manager.py`
- `uv run ruff check nanobot/acp tests/acp`

## Resume Instructions (Agent)

- This plan owns terminal process lifecycle and terminal state. Downstream tracks should treat it as a service.

## Decisions / Deviations Log

- 2026-03-09: Full ACP parity requires terminal lifecycle support, not a run-to-completion shell wrapper.
- 2026-03-09: Preferred initial strategy is managed `asyncio` subprocesses with explicit terminal state; PTY support is a scoped escalation, not the default assumption.
