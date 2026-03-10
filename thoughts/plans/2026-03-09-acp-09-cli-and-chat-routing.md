# ACP-09 CLI And Chat Routing

## Status

- ready

## Goal

- Bind nanobot chats and sessions to ACP-backed agent sessions and expose ACP mode through CLI and gateway wiring.

## Product intent alignment

- Advances Outcome 1 by making ACP sessions reachable through normal nanobot entrypoints.
- Advances Outcome 2 by preserving channel-native behavior while swapping backends.
- Supports Principles 1, 2, and 3.

## Dependencies

- `ACP-00`
- `ACP-02`
- `ACP-03`
- `ACP-06`
- `ACP-07`
- `ACP-08`

## File ownership

- `nanobot/cli/commands.py`
- `nanobot/agent/loop.py`
- `tests/acp/test_cli_routing.py`

## ACP interfaces consumed

- ACP config and session-binding records from `ACP-02`
- runtime session APIs and callback registration from `ACP-03`
- permission policy and decision events from `ACP-06`
- rendered update events from `ACP-07`
- OpenCode backend registration from `ACP-08`

## Acceptance criteria

- Nanobot can route a chat or CLI session to an ACP backend instead of the local LLM loop.
- Session binding is durable and recoverable.
- Progress, permission requests, and final completion all reach the user through the normal channel path.
- ACP backend selection is test-covered through config and any new CLI surface, while the local nanobot backend remains the default behavior when ACP is not configured.

## BDD scenarios

- Given a user starts an ACP-backed chat, when they send a prompt, then it routes to the bound OpenCode ACP session.
- Given a chat already has an ACP session binding, when the user sends a follow-up prompt, then nanobot reuses the same backend session.
- Given a session is cancelled or closed, when the user sends a new prompt, then nanobot resumes or creates a new backend session according to configured policy.

## Progress

- [x] ACP09.1 Add failing routing tests
- [x] ACP09.2 Wire ACP service into CLI and gateway startup
- [x] ACP09.3 Implement chat and session binding resolution
- [x] ACP09.4 Validate end-to-end prompt flow through the bus

## Phase 1

### End state

- ACP-backed sessions are reachable from normal nanobot entrypoints without breaking local-agent mode.

### Tests first

- Add failing CLI and gateway routing tests using `CliRunner` patterns and ACP fake runtime fixtures.

### Work

- Keep local nanobot behavior intact; ACP is a backend mode, not a total replacement.
- Minimize edits outside declared ownership.

### Verify

- `uv run pytest tests/acp/test_cli_routing.py tests/test_commands.py`
- `uv run ruff check nanobot tests/acp`

## Resume Instructions (Agent)

- This is the main integration track. Do not begin broad startup changes until the owned verify commands for `ACP-03`, `ACP-06`, `ACP-07`, and `ACP-08` are green and their importable interfaces are merged.

## Decisions / Deviations Log

- 2026-03-09: `nanobot/cli/commands.py` and `nanobot/agent/loop.py` are integration-owned files reserved for this track.
