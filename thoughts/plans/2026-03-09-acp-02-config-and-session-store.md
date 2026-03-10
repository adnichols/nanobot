# ACP-02 Config And Session Store

## Status

- ready

## Goal

- Add ACP configuration surface and durable nanobot-to-ACP session persistence.

## Product intent alignment

- Advances Outcome 1 by making ACP-backed sessions first-class nanobot state.
- Advances Outcome 3 by keeping backend configuration explicit and swappable.
- Supports Principles 1, 3, 4, and 5.

## Dependencies

- `ACP-00`
- `ACP-01`

## File ownership

- `nanobot/config/schema.py`
- `nanobot/session/manager.py`
- `nanobot/acp/store.py`
- `tests/acp/test_config_schema.py`
- `tests/acp/test_session_store.py`

## ACP interfaces consumed

- `ACPAgentDefinition` and session-record types from `ACP-01`
- `ACPSessionStore` protocol defined in `ACP-01`, implemented by this track

## Acceptance criteria

- Config supports ACP agent definitions, default agent selection, permission policy defaults, capability declarations, and process launch settings.
- Session persistence stores nanobot session key, ACP agent id, ACP session id, cwd, session config/mode metadata, and capability snapshot.
- Stored ACP session data can survive process restart and be loaded by later runtime tracks.
- `nanobot/acp/store.py` implements the shared `ACPSessionStore` contract with explicit methods for save, load, delete, and list operations used by `ACP-03`, `ACP-08`, `ACP-09`, and `ACP-10`.

## BDD scenarios

- Given an `opencode` ACP agent definition in config, when nanobot loads config, then command/env/policy fields validate cleanly.
- Given a nanobot chat binds to an ACP session, when the process restarts, then the binding can be recovered from persistent storage.
- Given multiple ACP agent definitions exist, when a session record is stored, then retrieval remains specific to both nanobot session and ACP backend.

## Progress

- [x] ACP02.1 Add ACP config models and validation
- [x] ACP02.2 Add ACP session record store
- [x] ACP02.3 Extend session persistence tests
- [x] ACP02.4 Prove shared store contract coverage for downstream consumers

## Phase 1

### End state

- ACP configuration and durable session binding exist behind tests.

### Tests first

- Add failing schema and session-store tests before implementation.
- Add failing tests that exercise the methods consumed by `ACP-03`, `ACP-08`, `ACP-09`, and `ACP-10` through the shared store protocol rather than direct implementation details.

### Work

- Keep ACP config separate from existing MCP config.
- Avoid CLI integration in this track.
- Implement only the storage methods required by the shared store contract and document any intentionally deferred fields in the record model.

### Verify

- `uv run pytest tests/acp/test_config_schema.py tests/acp/test_session_store.py`
- `uv run ruff check nanobot/config nanobot/session nanobot/acp tests/acp`

## Resume Instructions (Agent)

- This plan owns ACP schema and persistent session metadata. Do not edit CLI runtime wiring.

## Decisions / Deviations Log

- 2026-03-09: `nanobot/config/schema.py` and ACP session persistence are reserved for this track to reduce merge collisions.
