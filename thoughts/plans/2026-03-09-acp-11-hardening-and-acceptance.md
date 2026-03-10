# ACP-11 Hardening And Acceptance

## Status

- ready

## Goal

- Harden restart, resume, reconnect, and acceptance behavior and document the finished ACP mode.

## Product intent alignment

- Advances Outcomes 1 and 2 by raising ACP support to the reliability bar required for real use.
- Supports Principles 2, 3, and 4.

## Dependencies

- `ACP-00`
- `ACP-02`
- `ACP-03`
- `ACP-04`
- `ACP-05`
- `ACP-06`
- `ACP-07`
- `ACP-08`
- `ACP-09`
- `ACP-10`

## File ownership

- `tests/acp/test_recovery.py`
- `tests/acp/test_acceptance_opencode.py`
- `README.md`

## ACP interfaces consumed

- merged, stable runtime, storage, fs, terminal, permission, rendering, routing, and cron interfaces from `ACP-02` through `ACP-10`

## Acceptance criteria

- Restart recovery, `session/load`, dead-process reconnect, and cancellation edge cases are covered.
- There is a documented smoke-test path for a real `opencode acp` backend.
- README-level docs explain how to configure and use ACP mode.
- Real-backend smoke coverage is explicitly gated behind a pytest marker and environment switch so the default suite stays hermetic.

## BDD scenarios

- Given nanobot restarts with a saved ACP binding, when the backend supports `session/load`, then recovery succeeds without losing session mapping.
- Given the ACP child process dies unexpectedly, when the next prompt arrives, then nanobot reconnects or falls back predictably.
- Given a real OpenCode backend is available, when the smoke test runs, then the documented flow succeeds.

## Progress

- [x] ACP11.1 Add failing recovery tests
- [x] ACP11.2 Add acceptance and smoke coverage
- [x] ACP11.3 Patch edge cases discovered by full-stack testing
- [x] ACP11.4 Update README and operator docs
- [ ] ACP11.5 Feed major upstream design regressions back to owning tracks and re-run acceptance

## Phase 1

### End state

- ACP mode is resilient, documented, and acceptance-tested.

### Tests first

- Add failing tests for restart, load-session, reconnect, and cancel edge cases.
- Gate any real-backend smoke tests behind an explicit pytest marker such as `opencode_real` plus an opt-in environment variable so the default suite remains hermetic.

### Work

- Focus on last-mile reliability and docs rather than feature expansion.
- Feed any newly found design gaps back into the owning earlier tracks rather than solving them ad hoc here.

### Verify

- `uv run pytest tests/acp`
- `uv run ruff check .`

## Resume Instructions (Agent)

- Use this plan to close reliability gaps after the feature tracks land. Avoid opening new major subsystems here.
- Do not start this plan until all upstream plans have passed their owned verify commands and their interface-bearing files are merged on the target branch.

## Decisions / Deviations Log

- 2026-03-09: Acceptance coverage may include opt-in real OpenCode smoke tests, but the default suite must stay self-contained.
