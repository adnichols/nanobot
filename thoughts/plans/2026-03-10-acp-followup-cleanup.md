# ACP Follow-up Cleanup

## Status

- in_progress

## Goal

- Close the remaining ACP follow-up items: make the ACP-01 contract suite fully green without weakening tests, clean current repo Ruff violations, and document the exact prerequisites for opt-in OpenCode smoke tests.

## Product intent alignment

- Preserves Outcome 1 by keeping ACP's shared contract surface trustworthy.
- Supports Principle 4 by treating tests and lint as real quality gates instead of advisory output.

## Dependencies

- `thoughts/plans/2026-03-09-acp-orchestrator.md`

## File ownership

- `nanobot/acp/contracts.py`
- `nanobot/acp/runtime.py`
- `tests/acp/fakes/__init__.py`
- `tests/acp/test_contracts.py`
- `tests/acp/test_acceptance_opencode.py`
- `pyproject.toml`
- repo files touched by `ruff check .` remediation

## Acceptance criteria

- `tests/acp/test_contracts.py` passes without weakening the contract intent.
- `uv run ruff check .` passes.
- OpenCode smoke-test prerequisites are documented from repo-truth test wiring.

## BDD scenarios

- Given ACP runtime callback registration exists, when contract tests validate filesystem and terminal callback support, then the runtime exposes a verifiable dispatch surface instead of leaving expected failures.
- Given the repo has accumulated Ruff violations, when the cleanup runs, then lint passes without changing behavior.
- Given a developer wants to run real OpenCode smoke tests, when they follow the documented prerequisites, then they know exactly which env var, binary, marker, and command are required.

## Progress

- [x] AFU.1 Investigate and fix ACP-01 callback contract mismatch
- [x] AFU.2 Clean repo-wide Ruff violations and verify `uv run ruff check .`
- [x] AFU.3 Verify and document OpenCode smoke-test prerequisites

## Phase 1: Contract mismatch

### End state

- ACP callback contracts pass because the runtime exposes a concrete filesystem and terminal dispatch surface that matches the contract layer.

### Tests first

- Reproduce `tests/acp/test_contracts.py` failures and confirm the exact API mismatch before editing code.

### Work

- Fix the implementation instead of weakening tests unless investigation proves the tests are wrong and that decision is reviewed.

### Verify

- `uv run pytest tests/acp/test_contracts.py`

## Phase 2: Ruff cleanup

### End state

- Repo-wide Ruff passes.

### Tests first

- Reproduce `uv run ruff check .` failures and categorize safe autofixes vs manual edits.

### Work

- Apply the smallest behavior-preserving edits needed to satisfy Ruff.

### Verify

- `uv run ruff check .`

## Phase 3: Smoke-test prerequisites

### End state

- The exact requirements for running real OpenCode smoke tests are verified from code and docs.

### Tests first

- Inspect the marker, env-var gate, and command wiring in repo files.

### Work

- Keep the suite opt-in and document repo-truth requirements.

### Verify

- `uv run pytest tests/acp/test_acceptance_opencode.py -m opencode_real` remains opt-in unless `NANOBOT_TEST_OPENCODE=1` is set.

## Resume Instructions (Agent)

- Start with `AFU.1`.
- Do not weaken ACP contract tests without explicit human review.
- After lint cleanup, rerun the full Ruff gate.

## Decisions / Deviations Log

- 2026-03-10: Follow-up plan created after ACP orchestrator completion to close contract, lint, and smoke-test follow-ups.
- 2026-03-10: Root cause for the remaining ACP-01 failure is contract drift, not runtime absence. `nanobot/acp/contracts.py` and runtimes now expose concrete `handle_filesystem`/`handle_terminal` dispatch methods, but `tests/acp/test_contracts.py` still contains one pre-implementation expectation that `handle_permission()` raises `NotImplementedError`.
- 2026-03-10: Resolved the ACP-01 drift by aligning implementation and tests to the actual contract: runtimes now provide callback dispatch methods, the fake callback registry returns a deterministic denial when no handler is registered, and the permission-correlation test now asserts `verify_permission_correlation_contract()` instead of a bootstrap-era `NotImplementedError` expectation.
- 2026-03-10: `uv run ruff check .` is now green after applying safe autofixes plus small manual cleanups in tool, channel, provider, cron, and test files.
- 2026-03-10: Real OpenCode smoke tests are still opt-in. Repo-truth gate is `NANOBOT_TEST_OPENCODE=1 uv run pytest tests/acp/test_acceptance_opencode.py -v -m opencode_real`, and the local `opencode` binary is available on PATH. The marker is now registered in `pyproject.toml`, and the suite passes locally (11 passed).
- 2026-03-10: Replaced all remaining `datetime.utcnow()` usages in ACP code, ACP tests, and the remaining `mochat` call sites with timezone-aware UTC timestamps. Verification after cleanup: `uv run pytest tests/acp -q` -> `252 passed, 11 skipped`; `uv run ruff check .` -> clean.
