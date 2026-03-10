# ACP-00 Bootstrap Docs

## Status

- ready

## Goal

- Bootstrap `nanobot` for quality-gated, resumable, parallel ACP implementation work.

## Product intent alignment

- Advances Outcome 1 by creating the operating framework for ACP-backed sessions.
- Advances Outcome 3 by making external-agent work configurable and process-driven rather than platform-bound.
- Supports Principles 1, 3, and 5.

## Dependencies

- none

## File ownership

- `AGENTS.md`
- `thoughts/specs/product_intent.md`
- `thoughts/plans/AGENTS.md`

## Acceptance criteria

- Root repo guidance exists and matches repo truth.
- Product intent exists and explicitly covers ACP-backed agent delegation.
- Planning overrides exist and define the standard contract for all later ACP plans.
- Later ACP plans can cite these files as source of truth without ambiguity.
- The ACP program wave structure is documented so parallel execution order is explicit.

## BDD scenarios

- Given a new coding agent enters the repo, when it reads `AGENTS.md`, then it sees the real command set and phase-gated workflow.
- Given a planner starts a new ACP plan, when it reads `thoughts/plans/AGENTS.md`, then ownership and verification rules are explicit.
- Given an implementation proposal changes repo direction, when it conflicts with `thoughts/specs/product_intent.md`, then that conflict is blocking.

## Program wave structure

- Wave 0: `ACP-00`
- Wave 1: `ACP-01`
- Wave 2: `ACP-02`, `ACP-03`
- Wave 3: `ACP-04`, `ACP-05`, `ACP-06`
- Wave 4: `ACP-07`, `ACP-08`
- Wave 5: `ACP-09`
- Wave 6: `ACP-10`
- Wave 7: `ACP-11`

## Progress

- [ ] ACP00.1 Draft root contributor guide
- [ ] ACP00.2 Draft product intent
- [ ] ACP00.3 Draft local planning overrides
- [ ] ACP00.4 Review all bootstrap docs for coherence

## Phase 1

### End state

- Bootstrap docs exist and are internally consistent.

### Tests first

- N/A for doc-only work; use this repo-truth review checklist:
  - `pyproject.toml` confirms canonical CLI entrypoint and dev tooling
  - `README.md` confirms current operator commands and repo positioning
  - root file layout confirms there is no existing contributor `AGENTS.md`
  - `thoughts/specs/product_intent.md` and `thoughts/plans/AGENTS.md` stay aligned with `AGENTS.md`
  - no nonexistent build or e2e gate is introduced

### Work

- Encode current repo truth: `uv run ruff check .` and `uv run pytest` are the only canonical gates today.
- Encode the mandatory review loop and resumable plan structure.
- Encode ACP file-ownership rules for later parallel work.

### Verify

- Manual review against the checklist in `### Tests first`.

## Resume Instructions (Agent)

- Write only the bootstrap docs in this plan. Do not touch implementation files.

## Decisions / Deviations Log

- 2026-03-09: Bootstrap guidance reflects current repo truth and intentionally does not invent nonexistent build or e2e gates.
