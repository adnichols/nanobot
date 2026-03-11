# ACP Timeout Fix

## Status

- completed

## Goal

- Restore OpenCode ACP routing so nanobot no longer times out and falls back for a basic message when ACP is configured.

## Product intent alignment

- Advances Outcome 1 by keeping ACP-backed external agent sessions usable instead of silently degrading to the local loop.
- Supports Principle 3 by making external delegation feel native and resumable rather than fragile during session load.
- Supports Principle 5 by keeping ACP configuration explicit while ensuring the transport honors configured agent args.

## Dependencies

- `thoughts/specs/product_intent.md`
- `thoughts/plans/2026-03-09-acp-08-opencode-and-mcp.md`
- `thoughts/plans/2026-03-09-acp-09-cli-and-chat-routing.md`

## File ownership

- `nanobot/acp/sdk_client.py`
- `tests/acp/test_sdk_adapter.py`
- `thoughts/plans/2026-03-11-acp-timeout-fix.md`
- local user config `~/.nanobot/config.json`

## Acceptance criteria

- `SDKClient` can pass agent args like `acp` to `spawn_stdio_connection()` without raising argument binding errors.
- ACP config for the local `opencode-agent` launches OpenCode in ACP mode instead of the default TUI mode.
- The relevant ACP tests pass without weakening existing coverage.

## BDD scenarios

- Given an ACP agent definition includes args such as `acp`, when `SDKClient` spawns the stdio transport, then the ACP SDK receives the intended command and args without Python argument-binding failures.
- Given the local nanobot config points at OpenCode, when nanobot launches the ACP backend, then it starts `opencode acp` rather than bare `opencode`.
- Given ACP routing is enabled for a session, when nanobot sends a message, then ACP session setup can proceed instead of timing out before prompt delivery.

## Progress

- [x] ATF.1 Capture the failing behavior and lock the fix with focused tests
- [x] ATF.2 Fix ACP stdio spawn argument handling in `SDKClient`
- [x] ATF.3 Update local ACP config to launch OpenCode in ACP mode
- [x] ATF.4 Verify targeted ACP tests and a direct runtime smoke check

## Phase 1: Reproduce and lock behavior

### End state

- The repo has focused evidence and tests covering the ACP spawn-args path.

### Tests first

- Reproduce the current spawn failure and inspect existing ACP tests before editing code.

### Work

- Add or update a focused test that proves `SDKClient` forwards command args to `spawn_stdio_connection()` correctly.

### Verify

- `uv run pytest tests/acp/test_sdk_adapter.py -k spawn`

## Phase 2: SDK transport fix

### End state

- `SDKClient` spawns ACP agents with the configured args and no binding error.

### Tests first

- Run the focused spawn test in red state if possible.

### Work

- Patch `_spawn_connection()` with the smallest fix that preserves current behavior for env and cwd.

### Verify

- `uv run pytest tests/acp/test_sdk_adapter.py`

## Phase 3: Local ACP config fix

### End state

- The local OpenCode ACP agent config explicitly launches `opencode acp`.

### Tests first

- Inspect the active local config block before editing it.

### Work

- Add the missing ACP args to the local `opencode-agent` definition.

### Verify

- Confirm the local config contains `"args": ["acp"]`.

## Phase 4: End-to-end verification

### End state

- Targeted ACP tests pass and a direct message no longer times out before ACP initialization.

### Tests first

- Re-run the direct debug path after the code and config fixes are in place.

### Work

- Use the smallest runtime smoke check that exercises real ACP initialization without inventing new gates.

### Verify

- `uv run pytest tests/acp/test_sdk_adapter.py`
- `uv run python - <<'PY' ... PY`

## Resume Instructions (Agent)

- Start with `ATF.1`.
- Keep the code change limited to ACP transport spawning unless verification reveals another concrete blocker.
- Do not edit unrelated repo ACP routing code unless new evidence proves it is part of this bug.

## Decisions / Deviations Log

- 2026-03-11: Investigation found two separate causes behind ACP fallback: the local nanobot config launched bare `opencode` without `acp`, and `SDKClient._spawn_connection()` passed args to `spawn_stdio_connection()` in a way that breaks as soon as extra args are present.
- 2026-03-11: Live OpenCode probing showed a third transport mismatch in nanobot's ACP client layer: request params and response parsing still assumed older snake_case/schema-shaped payloads, while current OpenCode ACP expects camelCase JSON-RPC payloads like `protocolVersion`, `sessionId`, and `mcpServers` and returns dict-shaped responses.
- 2026-03-11: Even after the transport fixes, first-message ACP session startup took about 6.3 seconds on this machine, so the hardcoded 5 second ACP route timeout still forced a local fallback. The route timeout was raised to 60 seconds so normal first-session startup no longer trips the fail-open path.
- 2026-03-11: Verification results: `uv run ruff check nanobot/acp/sdk_client.py nanobot/acp/sdk_types.py nanobot/agent/loop.py tests/acp/test_sdk_adapter.py tests/acp/test_cli_routing.py` passed; `uv run pytest tests/acp/test_sdk_adapter.py tests/acp/test_cli_routing.py` passed (`39 passed, 3 skipped`); direct ACP smoke routing no longer fell back and returned `ACP session completed.` on the local OpenCode backend.
