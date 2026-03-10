# Local Planning Overrides For nanobot

## Objective

- This file adds repo-local planning rules for `nanobot` on top of the shared planning workflow.
- It is intentionally narrow: it captures the rules needed for lightweight assistant work, ACP integration, and parallel multi-agent execution in this repo.

## Required local inputs

- Product intent source of truth: `thoughts/specs/product_intent.md`
- Repo contributor guide: `AGENTS.md`
- Canonical plan output path: `thoughts/plans/<date>-<slug>.md`

## Repo-specific plan additions or overrides

- New execution-ready plans must use canonical headings from `AGENTS.md`.
- Every ACP plan must declare:
  - `Dependencies`
  - `File ownership`
  - ACP interfaces consumed from the contract track
  - explicit verify commands
- Shared interface publication must happen through importable Python modules under `nanobot/acp/`; prose-only "interface notes" are not sufficient.
- Every parallel plan must be written so one agent can execute it independently inside the same repo with minimal cross-track edits.
- Use stable progress IDs prefixed with the plan code, for example `ACP03.2`.
- Parallel programs must document explicit wave ordering in a bootstrap or program-index plan. References like `Wave 1` are not sufficient unless the waves are written down.
- Every execution-ready plan must include a clear reuse and dependency decision that covers:
  - in-repo components considered for reuse
  - stdlib/platform primitives considered for reuse
  - external components considered for reuse
  - chosen approach and why it wins
  - explicit user approval status for any new external dependency or component
- Plans may place this content in a dedicated section or in `Current implementation reality` plus `Locked decisions`, but it must be easy for another agent to find.

## Repo-specific TDD / BDD expectations

- ACP plans must include BDD coverage for happy path, failure path, restart/resume, and unattended automation where relevant.
- Contract and fake-runtime tests should land before broad implementation where practical.
- If a track depends on live binaries such as `opencode`, keep those checks opt-in and separate from the hermetic default suite.
- Plans that touch scheduler behavior must include cron/reminder scenarios, not only direct chat-driven prompts.

## Skill routing hints

- Repo bootstrap/process docs: `repo-agents-bootstrap`
- Initial design exploration: `brainstorming`
- Bug/test failure investigation: `systematic-debugging`
- Test-first contract work: `tdd-test-writer`
- Browser work is not a primary ACP concern here; only load browser-related skills when a plan actually needs them.

## Verify command requirements

- Canonical repo-wide verify commands today:
  - `uv run ruff check .`
  - `uv run pytest`
- Plans should also provide the smallest owned verify command, for example a targeted `pytest` module or directory.
- Do not add nonexistent build/e2e commands to a plan's `Verify` section unless the plan itself introduces and documents those commands.

## Legacy migration policy

- There are no existing planning docs in this repo that need preservation.
- All new ACP work should use the canonical plan format from day one.

## Local ready bar additions

- A plan is not ready unless file ownership is explicit enough to run in parallel with other tracks.
- A plan is not ready unless it explains what shared interfaces it consumes and which track owns those interfaces.
- A plan that touches channel delivery, permissions, or scheduling must include at least one cross-surface scenario proving the behavior in context.
- A plan is not ready unless it documents the reuse search it performed and explains why any custom build is necessary.
- A plan is not ready if it proposes a new external dependency without clearly flagging it and recording user approval status.

## Notes

- Keep this file additive. Repo-truth commands and contributor workflow belong in `AGENTS.md`, not here.
