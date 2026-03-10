# ACP-08 OpenCode And MCP

## Status

- ready

## Goal

- Make OpenCode the first supported ACP backend and pass MCP servers through correctly.

## Product intent alignment

- Advances Outcome 1 by delivering real ACP value against the target backend.
- Advances Outcome 3 by preserving backend configurability and tool extensibility.
- Supports Principles 1, 3, and 5.

## Dependencies

- `ACP-00`
- `ACP-01`
- consumes config and session interfaces from `ACP-02`
- integrates with runtime hooks from `ACP-03`

## File ownership

- `nanobot/acp/opencode.py`
- `tests/acp/test_opencode_integration.py`

## ACP interfaces consumed

- ACP agent config and session-binding records from `ACP-02`
- runtime launch/session interfaces from `ACP-03`
- shared MCP-server mapping types from `ACP-01`

## Acceptance criteria

- Nanobot can launch `opencode acp` as an ACP backend.
- New and loaded ACP sessions include the configured cwd and MCP server list.
- OpenCode-specific capability handling and load-session behavior are covered by tests.
- All OpenCode-specific behavior stays isolated in `nanobot/acp/opencode.py`; shared runtime and storage modules remain free of OpenCode-specific imports.

## BDD scenarios

- Given OpenCode is configured, when a nanobot ACP session starts, then `opencode acp` initializes successfully.
- Given MCP servers are configured in nanobot, when a new ACP session is created, then they are passed through to ACP session setup.
- Given OpenCode supports load-session, when nanobot resumes a saved session, then session recovery follows the advertised capability cleanly.

## Progress

- [x] ACP08.1 Add failing OpenCode integration tests
- [x] ACP08.2 Implement OpenCode launch adapter
- [x] ACP08.3 Implement MCP passthrough mapping
- [x] ACP08.4 Add resume and load-session coverage

## Phase 1

### End state

- OpenCode is the first-class ACP backend with MCP passthrough support.

### Tests first

- Add failing tests for launch args, session setup payload, MCP mapping, and load-session behavior.

### Work

- Keep provider-specific logic isolated in this module.
- Do not take ownership of CLI or bus routing.

### Verify

- `uv run pytest tests/acp/test_opencode_integration.py`
- `uv run ruff check nanobot/acp tests/acp`

## Resume Instructions (Agent)

- Optimize for OpenCode first, but do not bake OpenCode-only assumptions into the shared runtime or storage layers.

## Decisions / Deviations Log

- 2026-03-09: OpenCode is the reference ACP backend for the first implementation wave.
