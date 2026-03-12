# ACP Fallback Toggle

## Status

- completed

## Goal

- Make ACP fail-open fallback to the local nanobot agent configurable, with the default behavior changed to ACP-only when ACP routing is selected.

## Why this plan exists

- The current ACP path in `AgentLoop` silently falls back to the local loop on ACP timeout or error.
- The requested behavior is stricter: when ACP is configured and selected for a session, nanobot should not silently switch execution models unless explicitly configured to do so.
- We must preserve the fallback code path for operators who still want fail-open behavior, but make it opt-in instead of the default.

## Authority and inputs

- `AGENTS.md`
- `thoughts/plans/AGENTS.md`
- `thoughts/specs/product_intent.md`
- User request on 2026-03-11 to disable ACP fallback by default while keeping code available behind a configurable toggle.

## Current implementation reality

- `nanobot/agent/loop.py` routes to ACP when `acp_service` and `acp_default_agent` are present.
- On ACP timeout or error, `_process_message()` logs a warning and falls through to the local nanobot loop.
- `nanobot/config/schema.py` has ACP agent/process settings but no toggle controlling fail-open behavior.
- `nanobot/cli/commands.py` wires ACP service and default agent into `AgentLoop` for both `gateway` and `agent` entrypoints.
- Existing tests in `tests/acp/test_cli_routing.py` lock the current fallback behavior and must be updated to reflect the new default while preserving opt-in coverage.

## Progress

- [x] ACPFT.1 Add config surface for ACP local fallback policy with default disabled.
- [x] ACPFT.2 Wire the toggle through CLI/gateway into `AgentLoop` and preserve opt-in fail-open behavior.
- [x] ACPFT.3 Update and extend ACP tests for default ACP-only behavior and explicit fallback opt-in.
- [x] ACPFT.4 Verify with targeted tests and a live ACP smoke check.

## Resume instructions (agent)

- Read this file fully before editing.
- Find the first unchecked item in `## Progress` and complete work phase-by-phase.
- Keep the implementation limited to ACP config, ACP routing control, and tests unless verification exposes a directly related blocker.
- Do not weaken hermetic tests; use a live ACP smoke check only as an extra verification step.

## Product intent alignment

- Advances Outcome 1 by making ACP-backed sessions behave as a first-class execution mode instead of silently degrading into the local loop.
- Supports Principle 3 by keeping external delegation observable and honest about failure.
- Supports Principle 5 by making fallback behavior explicit and configurable in ACP config rather than hidden in routing code.

## Locked decisions

- The fallback code path stays in the repo.
- A new ACP config boolean will control whether nanobot may fail open from ACP into the local loop.
- The default value will disable fallback.
- When fallback is disabled and ACP fails, nanobot will surface an ACP error response instead of silently using the local loop.
- Entry points that build `AgentLoop` from config must pass the new toggle consistently.

## Acceptance criteria

- `ACPConfig` exposes a boolean toggle for local fallback from ACP.
- The toggle defaults to disabled.
- `AgentLoop` only falls back to the local loop when the toggle is explicitly enabled.
- When fallback is disabled and ACP times out or errors, the user receives an ACP failure response and local execution does not run.
- Existing local-only mode still works when ACP is not configured.
- Focused ACP tests cover both the default ACP-only path and the explicit fallback opt-in path.

## BDD scenarios

- Given ACP is configured and local fallback is disabled, when ACP raises an error, then nanobot returns an ACP failure response and does not invoke the local agent loop.
- Given ACP is configured and local fallback is disabled, when ACP times out, then nanobot cancels the ACP operation if possible, returns an ACP timeout response, and does not invoke the local agent loop.
- Given ACP is configured and local fallback is explicitly enabled, when ACP raises an error, then nanobot logs the ACP failure and falls back to the local agent loop.
- Given ACP is configured and local fallback is explicitly enabled, when ACP times out, then nanobot logs the timeout, cancels the ACP operation if possible, and falls back to the local agent loop.
- Given ACP is not configured, when a message is processed, then nanobot still uses the local agent loop as its selected mode rather than treating that as fallback.

## Phase 1: Config contract

### End state

- ACP config has an explicit local-fallback toggle with a safe default.

### Tests first

- Inspect existing ACP schema tests for the right place to assert the default and explicit override behavior.

### Work

- Add the config field to `ACPConfig` with naming and doc comments consistent with the existing schema.
- Update ACP config schema tests to lock the default and explicit opt-in values.

### Expected files

- `nanobot/config/schema.py`
- `tests/acp/test_config_schema.py`

### Verify

- `uv run pytest tests/acp/test_config_schema.py`

## Phase 2: Routing policy wiring

### End state

- `AgentLoop` knows whether ACP may fail open, and CLI/gateway pass the config consistently.

### Tests first

- Update ACP routing tests to describe the new default ACP-only behavior before changing code.

### Work

- Add an `AgentLoop` ACP fallback policy parameter with a default matching config.
- Pass the config from both `gateway` and `agent` construction sites.
- Change the ACP timeout/error branch so it returns an ACP failure response when fallback is disabled and only enters the local loop when fallback is enabled.

### Expected files

- `nanobot/agent/loop.py`
- `nanobot/cli/commands.py`
- `tests/acp/test_cli_routing.py`

### Verify

- `uv run pytest tests/acp/test_cli_routing.py -k "ACPFallback or acp_mode or local_mode"`

## Phase 3: Verification

### End state

- The owned tests pass and a live ACP smoke check confirms ACP still routes successfully under the new default.

### Tests first

- None beyond the updated focused tests.

### Work

- Run focused ACP schema and routing tests.
- Run one live ACP message smoke check to confirm real ACP still handles the request and no local fallback is required for the happy path.

### Expected files

- No additional file edits expected.

### Verify

- `uv run pytest tests/acp/test_config_schema.py tests/acp/test_cli_routing.py`
- `uv run python - <<'PY' ... PY`

## Verification strategy

- Prefer targeted pytest modules that cover the changed contract and routing behavior.
- Use a live ACP smoke check only to validate the real happy path still works with fallback disabled by default.
- Do not claim repo-wide validation unless `uv run ruff check .` and `uv run pytest` are actually run.

## Delivery order

1. Add config toggle and schema coverage.
2. Wire routing behavior and update ACP routing tests.
3. Run targeted verification and live ACP smoke check.

## Non-goals

- Removing the fallback code path.
- Changing ACP transport semantics beyond the fail-open policy.
- Changing local-agent behavior when ACP is not configured.
- Broad refactors of CLI or session management.

## Decisions / Deviations log

- 2026-03-11: Keep the fallback code present but make it opt-in; default behavior becomes ACP-only for ACP-selected sessions.
- 2026-03-11: Implemented `acp.allow_local_fallback` with a default of `False`, threaded it through `gateway` and `agent`, and changed ACP-selected timeout/error handling to return ACP failure responses unless fallback is explicitly enabled.
- 2026-03-11: Verification passed: `uv run pytest tests/acp/test_config_schema.py tests/acp/test_cli_routing.py`, `uv run ruff check nanobot/config/schema.py nanobot/agent/loop.py nanobot/cli/commands.py tests/acp/test_config_schema.py tests/acp/test_cli_routing.py`, and a live ACP smoke check returned `ACP ONLY MODE OK` with `allow_local_fallback=False`.
