# Repository Guide For Coding Agents

## Purpose and scope

- This file is the authoritative repo-specific operating guide for coding agents working in `nanobot`.
- If any other local prompt template or rule file disagrees with this file for contributor workflow, follow this file.
- `nanobot/templates/AGENTS.md` is a runtime prompt template for nanobot sessions, not a contributor process guide.

## Repo reality checks

- Treat this repo as a lightweight, local-first assistant project with real user-facing automation features.
- Never modify `.env*`, Telegram tokens, API keys, or local user config without explicit permission.
- Never add fake build or e2e steps to plans. Current repo-truth validation is lint + unit tests unless the repo later adds more gates.
- Prefer additive ACP work under `nanobot/acp/` and ACP-scoped tests under `tests/acp/`.
- Avoid broad refactors during parallel execution. Each plan owns a declared file set and should not drift outside it.

## Canonical commands

- Install deps: `uv sync`
- Run CLI help: `uv run nanobot --help`
- Run agent mode: `uv run nanobot agent`
- Run gateway mode: `uv run nanobot gateway`
- Lint: `uv run ruff check .`
- Format check/fix if needed: `uv run ruff format .`
- Full unit suite: `uv run pytest`
- Single test module: `uv run pytest tests/test_commands.py`
- Filtered tests: `uv run pytest -k "cron or acp"`

## Quality gates

Current repo-truth gate order:

1. `uv run ruff check .`
2. `uv run pytest`

Notes:

- There is no canonical build gate documented in repo truth today.
- There is no canonical e2e gate documented in repo truth today.
- Plans may propose those as future work, but must not claim them as current required gates without adding the real commands first.

## Planning and execution mode

- Every non-trivial change starts from a plan file under `thoughts/plans/`.
- Every plan must align to `thoughts/specs/product_intent.md`.
- Use one plan per implementation agent when work is intended to run in parallel.
- Each plan must include:
  - `Status`
  - `Goal`
  - `Product intent alignment`
  - `Dependencies`
  - `File ownership`
  - `Acceptance criteria`
  - `BDD scenarios`
  - `Progress` with stable IDs
  - phased execution blocks with `End state`, `Tests first`, `Work`, `Verify`
  - `Resume Instructions (Agent)`
  - `Decisions / Deviations Log`
- Phase loop is mandatory: implement one phase -> review -> re-review until critical issues are closed -> then advance.
- Tests-first is the default. If strict RED -> GREEN is skipped, the plan must explain why and define compensating verification.
- During parallel execution, agents must respect file ownership. Cross-track coordination happens by editing shared contract files only through the owning plan.

## Reuse and dependency doctrine

- Default order of preference:
  1. reuse existing in-repo componentry and extension points
  2. reuse standard-library or platform primitives
  3. reuse mature external components
  4. build custom code only when the above are insufficient
- Before proposing a new subsystem, abstraction, or dependency, inspect the repo for existing components, patterns, and storage/runtime surfaces that can be adapted.
- Prefer thin adapters around reused components over parallel implementations that duplicate behavior already present in the repo or platform.
- If external component reuse is being considered, agents must validate and record:
  - why in-repo reuse is insufficient
  - why stdlib/platform primitives are insufficient
  - maintenance activity and maturity
  - license compatibility
  - API stability and operational footprint
  - security and testability implications
- If a plan or implementation introduces a new external component or dependency, flag it clearly to the user and get explicit buy-in before proceeding with that dependency.
- Plans and final handoffs must call out what was reused, what remained custom, and why custom code was necessary.

## ACP program rules

- Shared ACP contracts and fake runtime belong to the contract track first. Downstream tracks must import those contracts instead of inventing local ones.
- `nanobot/config/schema.py` and ACP session persistence are owned by the config/store track.
- `nanobot/cli/commands.py` and `nanobot/agent/loop.py` are integration-owned files and should not be edited by lower-level tracks.
- Terminal lifecycle is a dedicated subsystem. Do not try to reuse `ExecTool` as full ACP terminal support.
- Scheduler behavior is a first-class product requirement. ACP work is not complete until cron/reminder flows are covered.

## Commit and handoff rules

- Commit messages should capture rationale, not only changed files.
- Do not mark work complete until the owned verify commands pass.
- Final handoff from each plan should include:
  - changed files
  - verification run and result
  - interface changes for other tracks
  - residual risks or follow-up issues

## Style and architecture guardrails

- Follow Ruff as formatter/linter authority.
- Prefer small, explicit Python modules over hidden framework magic.
- Prefer adaptation over reinvention when well-maintained internal or external components already solve the problem.
- Keep ACP transport/runtime, rendering, permissions, fs, and terminal concerns separated.
- Prefer deterministic tests with fakes over live external services.
- Treat restart/recovery and unattended cron behavior as correctness concerns, not polish.

## Worktree and environment notes

- Parallel plan execution should use separate git worktrees or branches to minimize file collisions.
- ACP integration work should assume local OpenCode availability only in opt-in acceptance tests, not base unit tests.
- If a test requires real external binaries, gate it explicitly and keep the default suite hermetic.

## Fast triage commands

- Repo status: `git status --short`
- ACP-focused tests: `uv run pytest tests/acp`
- Existing cron tests: `uv run pytest tests/test_cron_service.py`
- Existing command tests: `uv run pytest tests/test_commands.py`
