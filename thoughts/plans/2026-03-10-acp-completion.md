# ACP Completion Recovery

## Status

- in_progress

## Goal

- Finish the ACP implementation to the originally intended user-visible bar: real OpenCode-backed prompting, correct channel routing, real cancel/recovery behavior, scheduled ACP automation, and truthful acceptance coverage.

## Why this plan exists

- ACP was reported as complete, but the first real prompt path fails immediately because the production runtime still raises `RuntimeError("Real agent mode not fully implemented")` in `nanobot/acp/runtime.py`.
- Multiple ACP subsystems exist in isolation, but key integration seams remain incomplete: real transport, full agent-definition wiring, live channel delivery, `/stop` cancellation, cron/unattended policy, and restart/recovery semantics.
- Existing plans, docs, and tests overstate completion, so this recovery plan consolidates the remaining work into one execution-ready path with a stricter acceptance bar.

## Authority and inputs

- Root repo guidance: `AGENTS.md`
- Product intent: `thoughts/specs/product_intent.md`
- Local planning overrides: `thoughts/plans/AGENTS.md`
- Prior ACP program plans: `thoughts/plans/2026-03-09-acp-orchestrator.md`, `thoughts/plans/2026-03-09-acp-03-runtime-core.md`, `thoughts/plans/2026-03-09-acp-06-permission-broker.md`, `thoughts/plans/2026-03-09-acp-07-update-bridge-and-rendering.md`, `thoughts/plans/2026-03-09-acp-08-opencode-and-mcp.md`, `thoughts/plans/2026-03-09-acp-09-cli-and-chat-routing.md`, `thoughts/plans/2026-03-09-acp-10-cron-automation.md`, `thoughts/plans/2026-03-09-acp-11-hardening-and-acceptance.md`
- Follow-up cleanup context: `thoughts/plans/2026-03-10-acp-followup-cleanup.md`
- Validated code reality: `nanobot/acp/runtime.py`, `nanobot/acp/client.py`, `nanobot/acp/service.py`, `nanobot/acp/opencode.py`, `nanobot/acp/cron.py`, `nanobot/acp/render.py`, `nanobot/agent/loop.py`, `nanobot/cli/commands.py`, `tests/acp/*`, `README.md`

## Dependencies

- Existing ACP contracts, fake runtime, config schema, and session stores from ACP-01 and ACP-02 remain the foundation and must be reused.
- This plan depends on no new external library by default.
- If finishing the real transport requires a new external ACP client dependency beyond what is already available in-repo or in the existing environment, stop and get explicit user approval before adding it.

## File ownership

- `nanobot/acp/runtime.py`
- `nanobot/acp/client.py`
- `nanobot/acp/service.py`
- `nanobot/acp/opencode.py`
- `nanobot/acp/cron.py`
- `nanobot/acp/render.py`
- `nanobot/acp/updates.py`
- `nanobot/acp/permissions.py`
- `nanobot/agent/loop.py`
- `nanobot/cli/commands.py`
- `README.md`
- `tests/acp/test_runtime_core.py`
- `tests/acp/test_opencode_integration.py`
- `tests/acp/test_cli_routing.py`
- `tests/acp/test_cron_acp.py`
- `tests/acp/test_update_rendering.py`
- `tests/acp/test_acceptance_opencode.py`
- New ACP-scoped integration tests created under `tests/acp/` if needed to cover real end-to-end behavior

## ACP interfaces consumed from the contract track

- `ACPInitializeRequest`, `ACPPromptRequest`, `ACPCancelRequest`, `ACPLoadSessionRequest`
- `ACPStreamChunk`, `ACPStreamChunkType`, `ACPUpdateEvent`, `ACPSessionRecord`
- `ACPSessionStore`, `ACPCallbackRegistry`, `ACPUpdateSink`
- Existing permission broker, unattended policy, update accumulator, and session-binding contracts must be reused rather than redefined locally

## Current implementation reality

- Real ACP prompting is not implemented in the production runtime. `nanobot/acp/runtime.py` still contains a TODO for actual protocol communication and raises a runtime error instead of sending a real prompt.
- The production ACP entrypoint drops most configured agent settings. `nanobot/cli/commands.py` only passes the selected agent command into `ACPServiceConfig`, leaving `args`, `env`, `cwd`, policy, capabilities, and related settings unused by the live path.
- `OpenCodeBackend` exists as an adapter, but the live client/runtime path does not route through it, so OpenCode-specific launch and payload logic is not what `nanobot agent` actually uses.
- ACP routing returns CLI-only outbound messages even for non-CLI sessions and does not propagate `/stop` to ACP cancellation.
- Update rendering and permission handling are implemented as isolated subsystems but are not fully wired into the live ACP routing path.
- Cron ACP behavior is only partially represented in production. Gateway execution uses `cron:{job.id}` session keys instead of the originating chat session identity, and `ACPCronHandler` stores an unattended permission broker that it does not actually use.
- Session persistence exists, but current load/recovery behavior is primarily local-store replay rather than a verified real backend round-trip.
- The existing test suite is too fake-heavy or too shallow in the critical paths. The opt-in real OpenCode suite proves binary/config availability and `opencode acp --help`, not real prompting through nanobot.
- README ACP docs and orchestrator claims currently overstate completion and include stale policy naming.

## Progress

- [x] ACPC.1 Lock the missing end-to-end ACP behavior in failing tests
- [x] ACPC.2 Implement the real runtime transport and session lifecycle
- [ ] ACPC.3 Wire full agent definitions and OpenCode backend behavior into the live path
- [ ] ACPC.4 Complete live routing for channel delivery, updates, permissions, and `/stop`
- [ ] ACPC.5 Complete cron, unattended policy, and session reuse semantics
- [ ] ACPC.6 Harden recovery, correct docs, and prove acceptance end to end

## Resume Instructions (Agent)

- Read this file fully before editing code.
- Start with the first unchecked item in `## Progress` and execute phases in order.
- Keep work narrowly scoped to the owned files for the active phase.
- Use tests-first by default. If a planned RED step is temporarily impractical, record the exact reason in `## Decisions / Deviations Log` before continuing.
- After each phase: implement, run the phase verify commands, run a review/re-review loop until substantive issues are closed, then mark the corresponding progress item complete.
- Do not add a new dependency, weaken acceptance tests, or reclassify runtime-significant failures as follow-up work without explicit user approval.

## Product intent alignment

- Advances Outcome 1 by making ACP-backed external agent sessions actually usable through nanobot's agent and gateway entrypoints.
- Advances Outcome 2 by making scheduled reminders and recurring jobs work with ACP-backed sessions instead of only direct chat prompts.
- Advances Outcome 3 by preserving provider-agnostic ACP configuration while making OpenCode the first real backend that works end to end.
- Upholds Principle 2 by treating channels and automation as first-class ACP surfaces, not optional follow-up integration.
- Upholds Principle 3 by making external delegation observable, resumable, and delivered through the normal channel path.
- Upholds Principle 4 by enforcing unattended permission behavior during scheduled ACP work instead of leaving policy objects unused.

## Locked decisions

- Reuse the existing ACP contracts, stores, permission broker, update accumulator, renderer, and OpenCode adapter surfaces instead of introducing parallel implementations.
- Prefer adapting current in-repo ACP modules plus Python stdlib subprocess/stream primitives before considering any new external dependency.
- Treat `nanobot/acp/runtime.py` as the canonical place to finish real transport/lifecycle behavior; do not move runtime responsibility into unrelated layers.
- Lock the transport seam before implementation: the runtime will speak the existing ACP stdio protocol over newline-delimited JSON messages, reusing any already-available ACP helpers if present, and the implementation must record the exact framing/serialization evidence it follows in the phase log.
- Lock subprocess ownership: `ACPAgentRuntime` remains the single process owner for the live path, while `OpenCodeBackend` is limited to configuration, launch-argument/env/cwd construction, capability advertisement, and OpenCode-specific initialize/load/recovery payload translation unless execution evidence proves a deeper handoff is required.
- Preserve hermetic default tests. Real OpenCode binary tests remain opt-in behind `NANOBOT_TEST_OPENCODE=1` and the `opencode_real` marker.
- The completion bar is user-visible behavior, not adapter-only unit coverage. A plan phase is not complete until the real nanobot path it claims to enable is verified.
- README and plan/docs must be corrected to repo truth in the same program; inaccurate claims are part of the bug.
- Lock the scheduled-session policy: cron/reminder ACP execution reuses the originating `channel:chat_id` session binding by default; no isolated-session mode is introduced in this recovery plan unless the user explicitly asks for one later.
- No new external dependency is approved at plan time.

## Reuse and dependency decision

- In-repo components considered for reuse:
  - `ACPClient`, `ACPService`, session stores, binding stores, permission broker, unattended policy, update accumulator, renderer, and `OpenCodeBackend`
- Stdlib/platform primitives considered for reuse:
  - `asyncio` subprocess management, stream IO, task coordination, JSON handling, timeouts, and cancellation semantics
- External components considered for reuse:
  - the existing local `opencode` binary and any ACP SDK/runtime pieces already present in the repo environment
- Chosen approach:
  - finish the missing transport and wiring using the current in-repo ACP architecture plus stdlib primitives, threading the existing `OpenCodeBackend` and other ACP modules into the real path instead of creating a second runtime stack
- Why this wins:
  - it preserves the intended ACP layering, minimizes surface churn, keeps tests hermetic by default, and fixes the exact seams already promised by prior plans rather than replacing them with a new subsystem
- Approval status:
  - no new external dependency approved; stop and ask if one becomes necessary

## Acceptance criteria

- `uv run nanobot agent -m "..."` with ACP enabled sends a real prompt through the production ACP runtime and returns a real OpenCode-backed response instead of raising a stub error.
- Production ACP startup honors the selected agent definition end to end, including `command`, `args`, `env`, `cwd`, policy, capabilities, and other supported runtime settings.
- ACP replies, progress updates, and permission prompts preserve the originating `channel` and `chat_id` instead of hardcoding CLI delivery.
- `/stop` propagates to the active ACP session and cancels the in-flight backend operation.
- Scheduled ACP reminders and recurring jobs reuse the correct session identity or an explicitly defined isolated-session policy, obey unattended permission behavior, and deliver results back to the originating channel.
- Restart/load/recovery semantics are implemented and verified for both successful resume and deterministic failure/fallback cases.
- The default hermetic ACP suite and repo-wide quality gates pass, and the opt-in real OpenCode smoke suite proves real prompting through nanobot rather than only binary/help availability.
- README ACP documentation matches repo truth for configuration, policies, and operational expectations.

## BDD scenarios

- Given ACP is enabled with a valid OpenCode agent definition, when `uv run nanobot agent -m "Reply with exactly ACP_OK if ACP is active." --no-markdown` runs, then nanobot initializes the real ACP runtime, sends the prompt, streams or accumulates the response, and returns `ACP_OK` without hitting a stubbed exception.
- Given ACP is configured with non-default `args`, `env`, and `cwd`, when the production path creates the runtime, then those settings are honored exactly once and the backend launch matches configuration rather than silently dropping fields.
- Given a Telegram or other non-CLI session routes through ACP, when progress, permission requests, and final output are emitted, then all outbound messages retain the original channel/chat destination instead of falling back to `cli/direct`.
- Given a long-running ACP prompt is in flight, when the user issues `/stop`, then nanobot calls the ACP cancel path, the backend operation is cancelled, and the user receives a stop confirmation instead of only cancelling local tasks.
- Given a scheduled ACP reminder or recurring job runs unattended, when it needs permission-sensitive work, then the unattended policy resolves the request deterministically and the run does not hang waiting for interactive input.
- Given a scheduled ACP job belongs to an existing chat session, when it executes, then it reuses the correct ACP session binding or explicitly follows the documented isolated-session policy instead of inventing a `cron:{job.id}` identity that loses continuity.
- Given the ACP backend exits unexpectedly after a session has been bound, when nanobot resumes or reloads the session, then it either reconnects/resumes successfully or surfaces a deterministic, tested fallback path rather than pretending recovery succeeded.
- Given the opt-in real OpenCode acceptance suite runs with `NANOBOT_TEST_OPENCODE=1`, when the suite completes, then it proves a real nanobot-to-ACP prompt round-trip, cancellation coverage, and restart/load behavior rather than only startup/help-path smoke checks.

## Phase-by-phase execution plan

## Phase 1: Lock the missing end-to-end ACP contract

### End State

- The missing user-visible ACP behavior is captured in failing or newly strengthened tests that would have caught the shipped gaps immediately.

### Tests first

- Add or strengthen RED tests for: real runtime prompt round-trip, full agent-definition propagation, non-CLI channel/chat preservation, `/stop` cancellation, cron session reuse, unattended policy resolution, and restart/load fallback behavior.
- Include at least one counterexample for each seam where prior tests gave misleading passes, especially fake-mode runtime tests and startup-only OpenCode acceptance checks.
- Keep live-binary assertions opt-in and ensure hermetic tests fail for missing production behavior, not for environment setup.

### Expected files

- `tests/acp/test_runtime_core.py`
- `tests/acp/test_opencode_integration.py`
- `tests/acp/test_cli_routing.py`
- `tests/acp/test_cron_acp.py`
- `tests/acp/test_acceptance_opencode.py`
- New ACP integration test modules under `tests/acp/` only if an existing module cannot express the missing behavior clearly

### Work

- Turn the discovered gaps into behavior-focused tests tied directly to the acceptance criteria.
- Replace shallow real-backend smoke checks with nanobot-driven prompt/cancel/recovery assertions.
- Make the RED contract strong enough to reject adapter-only success, fake-only routing, and CLI-only delivery.

### Verify

- `uv run pytest tests/acp/test_runtime_core.py tests/acp/test_opencode_integration.py tests/acp/test_cli_routing.py tests/acp/test_cron_acp.py tests/acp/test_acceptance_opencode.py`

## Phase 2: Implement the real runtime transport and session lifecycle

### End State

- `ACPAgentRuntime` can initialize, prompt, stream or accumulate responses, cancel, shut down, and load/recover sessions through the real backend path without hitting stubbed code.

### Tests first

- Start from the Phase 1 RED tests covering prompt correlation, cancellation, backend exit, and load/recovery semantics.
- Add a failure-path test for unexpected backend exit during prompt handling.
- Add a boundary/parity test ensuring multiple ACP sessions remain isolated while using the real runtime lifecycle.
- Add a protocol-shape test that proves the runtime emits and parses the expected newline-delimited JSON ACP messages rather than only spawning a subprocess.

### Expected files

- `nanobot/acp/runtime.py`
- `nanobot/acp/client.py`
- `nanobot/acp/service.py`
- `tests/acp/test_runtime_core.py`
- `tests/acp/test_acceptance_opencode.py`

### Work

- Replace the stubbed prompt path with the actual ACP stdio/session protocol implementation, using newline-delimited JSON framing consistent with the existing ACP request/response shapes and any already-available helper code.
- Implement real request/response correlation, lifecycle management, cancellation, shutdown cleanup, and load/recovery behavior.
- Preserve the existing fake-mode path for hermetic tests while making the production path genuinely functional.

### Verify

- `uv run pytest tests/acp/test_runtime_core.py`
- `uv run pytest tests/acp/test_acceptance_opencode.py -m "not opencode_real"`
- `uv run nanobot agent -m "Reply with exactly ACP_OK if ACP is active." --no-markdown`

## Phase 3: Wire full agent definitions and OpenCode backend behavior into the live path

### End State

- The production ACP path uses the selected agent definition completely and routes OpenCode-specific behavior through the intended adapter/runtime seam.

### Tests first

- Add RED coverage proving the live path preserves `command`, `args`, `env`, `cwd`, policy, capabilities, and any supported process settings.
- Add a counterexample showing that passing only the command is insufficient and would regress real backend launches.
- Cover both direct CLI agent mode and gateway initialization so the same configuration contract holds across surfaces.
- Use at least one non-default `args`, `env`, and `cwd` fixture in the test setup so the phase cannot pass on default-only connectivity.

### Expected files

- `nanobot/cli/commands.py`
- `nanobot/acp/service.py`
- `nanobot/acp/client.py`
- `nanobot/acp/opencode.py`
- `tests/acp/test_opencode_integration.py`
- `tests/acp/test_cli_routing.py`

### Work

- Thread the full `ACPAgentDefinition` through the live startup path instead of only the command string.
- Reuse `OpenCodeBackend` for launch-command/env/cwd assembly plus OpenCode-specific initialize/load/recovery payload translation, while keeping live subprocess creation and stdio ownership in `ACPAgentRuntime`.
- Ensure startup behavior matches README truth after the docs are corrected in the final phase.

### Verify

- `uv run pytest tests/acp/test_opencode_integration.py tests/acp/test_cli_routing.py`
- `uv run pytest -k "acp and (opencode or cli_routing)"`

## Phase 4: Complete live routing for channel delivery, updates, permissions, and `/stop`

### End State

- ACP sessions deliver progress, permission requests, and final answers through the normal outbound channel path, and `/stop` cancels the active ACP operation.

### Tests first

- Add RED coverage for non-CLI channel preservation, progress rendering, permission-request routing, duplicate suppression, and `/stop` -> ACP cancel propagation.
- Include a parity test proving CLI and non-CLI paths differ only in destination metadata, not in ACP behavior.
- Include a negative-path test showing permission handling does not silently bypass the broker when interactive approval is required.
- Add an ACP-mode command test proving `/stop` triggers ACP cancellation and returns a stop acknowledgement tied to the original channel/chat instead of only cancelling local loop work.

### Expected files

- `nanobot/agent/loop.py`
- `nanobot/acp/service.py`
- `nanobot/acp/updates.py`
- `nanobot/acp/render.py`
- `nanobot/acp/permissions.py`
- `tests/acp/test_cli_routing.py`
- `tests/acp/test_update_rendering.py`
- `tests/acp/test_permission_broker.py`

### Work

- Preserve source `channel` and `chat_id` through ACP routing.
- Subscribe the live routing path to the update accumulator/renderer so streamed ACP updates reach users through the existing message bus flow.
- Wire permission requests and decisions through the broker.
- Propagate `/stop` to `ACPService.cancel_operation()` and keep the user-facing stop acknowledgement coherent.

### Verify

- `uv run pytest tests/acp/test_cli_routing.py tests/acp/test_update_rendering.py tests/acp/test_permission_broker.py`

## Phase 5: Complete cron, unattended policy, and session reuse semantics

### End State

- Scheduled ACP jobs use the right session identity, apply unattended policy deterministically, and deliver results back to the originating channel.

### Tests first

- Add RED coverage for reminder and recurring-job ACP flows using the real production session-key rules.
- Add a counterexample proving `cron:{job.id}` breaks continuity when a chat session already exists.
- Add a guardrail test proving unattended jobs resolve permission-sensitive work without hanging and without pretending interactive permission occurred.
- Add an explicit regression test for gateway cron execution proving session keys derive from the originating `channel:chat_id` and/or existing binding lookup rather than `cron:{job.id}`.

### Expected files

- `nanobot/cli/commands.py`
- `nanobot/acp/cron.py`
- `nanobot/agent/tools/cron.py`
- `tests/acp/test_cron_acp.py`
- `tests/test_cron_service.py`

### Work

- Implement the locked scheduled-session rule by replacing `cron:{job.id}` with originating `channel:chat_id` session derivation and binding reuse in the production gateway callback.
- Route production scheduler execution through the real ACP cron integration, not a test-only semantic fork.
- Wire the unattended permission broker into the actual ACP cron execution path instead of only storing it on `ACPCronHandler`.
- Add explicit binding lookup behavior so scheduled jobs reuse an existing ACP session when one is already associated with the originating chat session.
- Preserve existing channel delivery semantics for reminder output.

### Verify

- `uv run pytest tests/acp/test_cron_acp.py tests/test_cron_service.py`

## Phase 6: Harden recovery, correct docs, and prove acceptance end to end

### End State

- ACP recovery behavior is verified, docs match repo truth, and both hermetic and opt-in real acceptance checks prove the implementation is actually complete.

### Tests first

- Add or strengthen tests for successful reload, deterministic fallback when resume is impossible, and dead-process recovery expectations.
- Add a real-backend acceptance scenario that runs through nanobot prompt/cancel/recovery behavior rather than binary/help-path smoke.
- Add a docs-truth check pass during review so no stale policy names or unsupported config examples remain.
- Add a real-backend config-propagation scenario using non-default `args`, `env`, or `cwd` so final acceptance proves more than basic connectivity.

### Expected files

- `nanobot/acp/runtime.py`
- `nanobot/acp/service.py`
- `README.md`
- `tests/acp/test_runtime_core.py`
- `tests/acp/test_acceptance_opencode.py`
- Any ACP test file updated to align final verified behavior with repo truth

### Work

- Finish any remaining recovery or deterministic-failure behavior needed for session load/restart claims.
- Update README ACP docs to match the actual supported configuration and operational behavior, including correcting policy naming from `never` to `deny` if that remains the repo-truth schema.
- Reconcile any overclaimed status or acceptance language in ACP planning artifacts if execution notes require it, without weakening the implementation bar.
- Run the repo-wide gates and the opt-in real OpenCode suite only after the hermetic ACP suite is green.

### Verify

- `uv run ruff check .`
- `uv run pytest`
- `NANOBOT_TEST_OPENCODE=1 uv run pytest tests/acp/test_acceptance_opencode.py -v -m opencode_real`
- `uv run nanobot agent -m "Reply with exactly ACP_OK if ACP is active." --no-markdown`

## Verification strategy

- Phase-level verification uses the smallest targeted `pytest` modules that prove the owned behavior.
- Repo truth gates must run in order before the plan is marked complete:
  1. `uv run ruff check .`
  2. `uv run pytest`
- Real OpenCode acceptance remains opt-in and runs only after the hermetic suite is green:
  - `NANOBOT_TEST_OPENCODE=1 uv run pytest tests/acp/test_acceptance_opencode.py -v -m opencode_real`
- Final manual smoke verification is required because the reported failure happened on the first real CLI interaction:
  - `uv run nanobot agent -m "Reply with exactly ACP_OK if ACP is active." --no-markdown`

## Delivery order

1. Phase 1 to lock the missing behavior into tests
2. Phase 2 to make the real runtime path functional
3. Phase 3 to honor the configured agent definition and OpenCode adapter behavior
4. Phase 4 to finish user-visible routing, permission, and stop semantics
5. Phase 5 to complete scheduler/unattended ACP behavior
6. Phase 6 to harden recovery, correct docs, and prove final acceptance

## Non-goals

- Introducing a new provider/backend beyond finishing the existing OpenCode ACP path
- Broad refactors outside ACP-owned integration surfaces
- Replacing the existing ACP architecture with a parallel runtime stack
- Adding build or e2e gates that do not exist in repo truth today
- Weakening tests or redefining acceptance to match the current incomplete implementation

## Decisions / Deviations Log

- 2026-03-10: Created this recovery plan after validating that ACP completion claims exceeded repo truth. The highest-risk gaps are real prompt transport, full agent-definition wiring, live channel delivery, `/stop` cancellation, cron/unattended policy, and recovery semantics.
- 2026-03-10: Chosen approach is to finish the existing ACP architecture rather than replace it. Current in-repo components are sufficiently mature that the missing work is integration and transport completion, not greenfield design.
- 2026-03-10: No new external dependency is approved in advance. If finishing real transport proves impossible with the current environment and stdlib/in-repo surfaces, implementation must pause for explicit approval.
- 2026-03-10: Clarified post-review execution constraints: lock transport framing to newline-delimited JSON ACP messages, keep subprocess ownership in `ACPAgentRuntime`, reuse `OpenCodeBackend` only for configuration/payload translation, require non-default config propagation checks, and lock cron session reuse to the originating `channel:chat_id` binding for this recovery plan.
- 2026-03-10: ACPC.2 COMPLETE - Implemented real ACP stdio protocol in `runtime.py`. Replaced stub error with actual newline-delimited JSON message sending/receiving. Implemented content_delta, tool_call, error, and done message types. Process properly manages stdio pipes (stdin, stdout, stderr) with asyncio subprocess. Cancellation and shutdown properly terminate agent process.
- 2026-03-10: Review-driven regression fix slice advanced ACPC.3 and ACPC.4 without closing either phase: `ACPService.load_session()` now preserves the configured `ACPAgentDefinition`, runtime launch no longer duplicates `acp` when args already include it, real prompt flow emits `prompt_start`/`prompt_end` with a shared correlation id, `_route_to_acp()` derives non-CLI destinations from `session_key`, and `/stop` again publishes through the bus while propagating ACP cancellation.

## Plan Changelog

- 2026-03-10: Initial execution-ready recovery plan created to replace overclaimed ACP completion with a verifiable finish line.
- 2026-03-10: Tightened the plan after review feedback by adding ACP contract-interface references, explicit transport/process-ownership decisions, stronger `/stop` and cron session-key tests, explicit unattended-permission wiring work, and stronger final verification for non-default agent settings.
