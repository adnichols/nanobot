# 2026-03-11 - Homebrew support and service rollout

## Status

- In progress

## Goal

- Make `nanobot` installable from an in-repo Homebrew tap and support `brew services` for `nanobot gateway`, with repo automation that refreshes the formula on release.

## Product intent alignment

- Advances the lightweight control-plane goal by reducing local setup friction for the `gateway` runtime.
- Reinforces unattended automation expectations by giving the gateway a first-class service manager path with restart behavior owned by Homebrew.
- Keeps the install path explicit and observable: release automation updates the formula in-repo rather than hiding packaging state elsewhere.

## Dependencies

- Reuse existing package metadata from `pyproject.toml` and dependency metadata from PyPI/Homebrew tooling; no new runtime dependency is introduced into `nanobot` itself.
- Reuse Homebrew's `virtualenv_install_with_resources` and `brew update-python-resources` instead of hand-maintaining Python resources.
- Reuse GitHub Actions first-party actions only for release automation.

## File ownership

- Owned by this plan:
  - `Formula/nanobot.rb`
  - `scripts/update_homebrew_formula.py`
  - `.github/workflows/update-homebrew-formula.yml`
  - `README.md`
  - `tests/test_homebrew_formula.py`
  - `thoughts/plans/2026-03-11-homebrew-support.md`
- Out of scope:
  - ACP implementation files already modified in the current worktree
  - user config files under `~/.nanobot/`

## Acceptance criteria

- Homebrew users can tap this repo and install `nanobot` via `brew install`.
- The formula exposes a `brew services` entry that runs `nanobot gateway` with persistent logs/state directories.
- The repo contains automation to refresh the formula on release publication without manual formula editing.
- Repo docs explain the supported Homebrew install/upgrade/service flow and clearly state the local-upgrade requirement for restarts.
- Automated tests cover the formula generator's critical rendering behavior.

## BDD scenarios

### Scenario: generate a fresh Homebrew formula

- **Given** a released `nanobot-ai` version and its source artifact metadata
- **When** the formula update script runs
- **Then** it writes `Formula/nanobot.rb` with the matching version, source checksum, Homebrew service block, and generated Python resources.

### Scenario: refresh the formula on release

- **Given** a GitHub release is published for a new `nanobot` version
- **When** the release workflow runs on the target branch
- **Then** it regenerates the Homebrew formula and commits the update if the generated file changed.

### Scenario: run nanobot as a Homebrew service

- **Given** a user has installed the tap formula and completed `nanobot onboard`
- **When** they run `brew services start nanobot`
- **Then** Homebrew launches `nanobot gateway` as a managed service using the formula's declared working directory and log files.

## Progress

- [x] HBS.1 Inspect release/install constraints and choose the Homebrew packaging approach.
- [x] HBS.2 Add a deterministic formula generator plus unit coverage.
- [x] HBS.3 Add release automation to refresh the formula on publish.
- [x] HBS.4 Document Homebrew install, upgrade, and service semantics in the README.
- [x] HBS.5 Run repo quality gates and record results.

## Phase 1 - Packaging approach and generator

### End state

- The repo has a generator script and checked-in formula that encode the Homebrew install/service contract.

### Tests first

- Add unit tests for formula rendering before finalizing the generator behavior.
- Strict RED/GREEN on the full formula resource block is impractical because resource generation depends on Homebrew/PyPI state; compensate with deterministic rendering tests plus a local generator dry run.

### Work

- Implement `scripts/update_homebrew_formula.py` to derive version/source metadata, call `brew update-python-resources`, and render the final formula.
- Check in `Formula/nanobot.rb` generated from the current package release.
- Capture Homebrew service defaults for `nanobot gateway`.

### Verify

- `uv run pytest tests/test_homebrew_formula.py`
- `python3 scripts/update_homebrew_formula.py --version 0.1.4.post3`

## Phase 2 - Release automation and docs

### End state

- Releases can refresh the formula in-repo automatically, and docs show users how to install and operate the Homebrew-managed service.

### Tests first

- Reuse Phase 1 unit coverage; add workflow/doc changes only after the generator contract is in place.

### Work

- Add a GitHub Actions workflow that runs the generator on release publication and commits formula changes back to the target branch.
- Update `README.md` with Homebrew install commands, service commands, and the limitation that remote deploys do not directly restart user machines without a local upgrade/bundle step.
- Update this plan's progress and decision log as implementation choices land.

### Verify

- `uv run pytest tests/test_homebrew_formula.py`
- `uv run ruff check .`
- `uv run pytest`

## Resume Instructions (Agent)

- Re-read `AGENTS.md` and this plan before resuming.
- Keep changes scoped to the owned files above; do not touch the ACP files already modified in the worktree.
- If Homebrew resource generation proves platform-sensitive, preserve the generator/test contract and document the exact limitation in the decision log before widening scope.

## Decisions / Deviations Log

- 2026-03-11: Reused Homebrew's Python formula tooling (`virtualenv_install_with_resources` + `brew update-python-resources`) instead of inventing a custom dependency-to-resource generator; in-repo logic stays a thin renderer/orchestrator.
- 2026-03-11: Treat "restart automatically on deploy" as "Homebrew-managed service restarts when the local machine upgrades the formula" because repo-side deploys cannot directly force a restart on user machines through Homebrew alone.
- 2026-03-11: `brew audit` required explicit `libyaml` and Homebrew-style dependency ordering, so the generator now bakes those into the formula output instead of relying only on generated Python resources.
- 2026-03-11: Homebrew/Linux source installs failed on transitive `hf-xet` because its Rust/C toolchain path pulled in `aws-lc-sys` and hit an optimization-sensitive build failure; the formula generator now strips `hf-xet` from Homebrew resources because `huggingface_hub` can run without it.
- 2026-03-11: The released package failed hard on newer config files by discarding the entire config when top-level unknown keys appeared. Fixed this in `nanobot/config/loader.py` by pruning only `extra_forbidden` paths during validation retries so older/newer config shapes degrade gracefully instead of losing provider credentials.
