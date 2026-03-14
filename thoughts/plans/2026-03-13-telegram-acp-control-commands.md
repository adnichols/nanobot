# Telegram ACP Control Commands

## Status

- ready

## Goal

- Add nanobot-owned Telegram control commands for ACP agent selection, model selection, and ACP-history session selection so Telegram can manage OpenCode-backed work predictably across restarts without depending on backend-specific slash-command UX.

## Why this plan exists

- Telegram already forwards arbitrary slash commands into ACP, but that only helps when the configured ACP backend advertises and correctly implements those commands.
- The user wants first-class Telegram controls for choosing the ACP agent, switching the active model, and resuming prior OpenCode sessions from ACP history.
- `SDKClient` already supports ACP `session/load` and `session/set_model`, and nanobot already persists ACP chat-to-session bindings, so the missing work is primarily gateway-owned control semantics, persistence, and Telegram UX.
- The current ACP service bootstrap is pinned to one `default_agent`, which makes multi-agent Telegram control impossible without explicit nanobot-side routing work.

## Authority and inputs

- `AGENTS.md`
- `thoughts/plans/AGENTS.md`
- `thoughts/specs/product_intent.md`
- User clarification on 2026-03-13: `/session` should select from OpenCode sessions that exist in ACP history, not from nanobot local chat history.
- Existing related implementation plan: `thoughts/plans/2026-03-12-telegram-acp-slash-command-routing.md`
- Validated implementation surfaces: `nanobot/agent/loop.py`, `nanobot/channels/telegram.py`, `nanobot/cli/commands.py`, `nanobot/acp/service.py`, `nanobot/acp/store.py`, `nanobot/acp/sdk_client.py`, `nanobot/acp/interfaces.py`, `nanobot/config/schema.py`, `tests/test_telegram_channel.py`, `tests/acp/test_cli_routing.py`, `tests/acp/test_sdk_adapter.py`

## Dependencies

- `thoughts/plans/2026-03-12-telegram-acp-slash-command-routing.md`
- `thoughts/plans/2026-03-09-acp-02-config-and-session-store.md`
- `thoughts/plans/2026-03-09-acp-03-runtime-core.md`
- `thoughts/plans/2026-03-09-acp-08-opencode-and-mcp.md`
- `thoughts/plans/2026-03-09-acp-09-cli-and-chat-routing.md`

## File ownership

- `nanobot/agent/loop.py`
- `nanobot/channels/telegram.py`
- `nanobot/cli/commands.py`
- `nanobot/acp/service.py`
- `nanobot/acp/sdk_client.py`
- `nanobot/acp/store.py`
- `nanobot/acp/interfaces.py`
- `nanobot/config/schema.py` (only if binding metadata or explicit config validation needs expansion)
- `tests/test_telegram_channel.py`
- `tests/acp/test_cli_routing.py`
- `tests/acp/test_session_store.py`
- `tests/acp/test_sdk_adapter.py`

## ACP interfaces consumed

- `ACPAgentRuntime.load_session()` via `SDKClient.load_session()`
- `SDKClient.set_model()` for ACP `session/set_model`
- `ACPSessionStore.list_sessions()` for persisted ACP-history enumeration
- `ACPSessionBindingStore` / `ACPSessionBinding` for chat-to-ACP binding persistence
- `ACPUpdateSink` and ACP advertised command discovery for Telegram command registration

## Current implementation reality

- Telegram already forwards arbitrary slash commands into the normal bus and ACP path, with `/command@botname` normalization and metadata preservation, and only keeps `/new`, `/help`, and `/stop` local in ACP mode.
- Telegram command registration already merges nanobot-local commands with ACP-advertised `available_commands_update` commands, but the local command catalog currently exposes only the existing baseline controls.
- `SDKClient` already supports `load_session(session_id)` and `set_model(model, session_id)` and waits for model-settle before prompting, so model/session control can reuse existing protocol calls rather than inventing a new ACP transport.
- `ACPService` already persists per-chat ACP bindings through `ACPSessionBindingStore`, but the binding schema only stores `acp_agent_id`, `acp_session_id`, `cwd`, `metadata`, and `capabilities`; it does not yet persist a nanobot-owned model override or any per-chat control metadata.
- `ACPFileSessionStore.list_sessions()` can enumerate persisted ACP history from disk, sorted by `updated_at`, but the current OpenCode-backed path does not yet populate that store from `SDKClient` or `ACPService`. This plan therefore must add explicit production writes/updates for `ACPSessionRecord`s before `/session list` can rely on ACP history as a real source of truth.
- `ACPService` bootstrap in `nanobot/cli/commands.py` is currently tied to a single `default_agent` definition and one permission-broker factory derived from that agent, so per-chat agent switching is not possible without refactoring the service bootstrap path. The plan must treat this as a safety-critical rebinding problem: selected agent changes need fresh `policy`, `env`, `cwd`, callback wiring, and permission-broker construction per chat instead of reusing the default-agent path.
- `AgentLoop` currently has no local handling for `/agent`, `/model`, or `/session`, so all three would either fall through to the ACP backend or fail silently depending on the backend command catalog.
- Existing session management in `nanobot/session/manager.py` lists nanobot local chat histories, not ACP/OpenCode history, and must remain out of scope for `/session` in this plan.
- Reuse and dependency decision:
- Reuse in-repo surfaces: `TelegramChannel`, `AgentLoop`, `ACPService`, `SDKClient`, `ACPFileSessionStore`, `ACPSessionBindingStore`, and existing ACP update wiring.
- Reuse stdlib/platform primitives: existing JSON persistence in the ACP stores, existing asyncio command-routing flow, and existing `python-telegram-bot` command menu registration.
- External components considered: direct reuse of `opencode-telegram` was rejected because the user wants this capability inside nanobot's ACP gateway architecture, not by adding a parallel wrapper dependency.
- Chosen approach: extend nanobot's existing ACP service and Telegram control plane with thin adapters over current stores and SDK calls; no new dependency is needed and user approval for any new external dependency is not granted or needed.

## Progress

- [ ] TGCTRL.1 Lock the control-command contract and persistence model with failing tests.
- [ ] TGCTRL.2 Teach the ACP service to switch agents, persist model overrides, and enumerate ACP-history sessions.
- [ ] TGCTRL.3 Intercept `/agent`, `/model`, and `/session` in `AgentLoop` with nanobot-owned semantics.
- [ ] TGCTRL.4 Update Telegram command registration and status/help text to surface the new control plane cleanly.

## Resume Instructions (Agent)

- Read this plan fully before editing code.
- Confirm the owned file set before starting and do not drift outside it unless a logged deviation becomes necessary.
- Start with the first unchecked item in `## Progress`.
- Execute one phase at a time using a tests-first loop, then run the phase verify commands, then perform a review/fix pass before moving to the next phase.
- Preserve the locked semantics for `/session`: it must operate on ACP/OpenCode history, not nanobot local conversation files.
- Keep unattended cron ACP behavior unchanged while modifying interactive Telegram control flows.
- Ask the user only if implementation proves that OpenCode ACP history cannot supply enough identity or timestamp data for a minimally usable `/session list` response.

## Product intent alignment

- Advances Outcome 1 by making Telegram a stronger ACP control plane for backend routing, session continuity, and model choice.
- Preserves Outcome 2 by keeping scheduler and unattended flows separate from interactive Telegram control semantics.
- Advances Outcome 3 by building provider-agnostic ACP controls inside nanobot rather than binding Telegram to a one-off external wrapper.
- Supports Principle 2 by treating Telegram as a first-class control surface instead of a thin prompt-only bridge.
- Supports Principle 3 by making ACP session selection and restart recovery native and resumable from Telegram.
- Supports Principle 4 by keeping interactive control metadata explicit and avoiding any hidden weakening of unattended permission policy.
- Supports Principle 5 by reusing explicit ACP config and storage surfaces instead of inventing opaque Telegram-only state.

## Locked decisions

- `/agent`, `/model`, and `/session` are nanobot-owned Telegram control commands; they are not passed through to ACP as ordinary slash-command content.
- `/session` operates only on ACP/OpenCode session history known to nanobot's ACP persistence layer; it does not list or manipulate nanobot local chat history.
- `/session new` is the explicit fresh-session control command for this feature set; existing `/new` behavior remains intact and compatible.
- `/agent use <id>` switches the Telegram chat to the selected configured ACP agent, rebuilds the per-chat ACP client and permission-broker wiring for that agent, and starts a fresh ACP session binding for that agent rather than trying to auto-resume a previous agent-local session in v1.
- Bare `/model` is the read-only status form and returns the current effective model for the chat (persisted override if present, otherwise the selected agent's configured default model, otherwise `unset`).
- `/model <model-id>` persists a nanobot-owned per-chat model override that is reapplied on ACP session load/create so behavior survives restart and backend variability.
- `/agent use <id>` clears any existing `model_override` for the chat before creating the fresh session for the new agent. Users can then set a new model explicitly for that agent; this avoids carrying incompatible model IDs across provider/agent boundaries.
- `/new` and `/session new` preserve the selected `agent_id` and persisted `model_override` for the chat while rotating only the bound ACP session id; they are fresh-session controls, not full control-state resets.
- `/session resume <id>` rebinds the Telegram chat to the selected ACP history session for the currently selected agent and then loads that session through ACP.
- `/session list` only needs to expose enough metadata for human selection in Telegram v1: short session ID, updated time, and any already-persisted metadata that is reliably available. Rich summaries are deferred.
- ACP-history session listing and resume must be agent-aware. The implementation will persist `agent_id` into ACP session-record metadata (and backfill/derive where possible for existing records) before `/session list` or `/session resume` filters by the currently selected agent.
- Telegram command registration always includes the local control commands even if the ACP agent does not advertise equivalent slash commands.
- Telegram command menus are global, so the ACP-advertised portion of the Telegram menu is the deduplicated union of advertised commands across configured ACP agents, while the agent-specific runtime behavior remains per chat.
- No new external dependency is approved or needed for this work.

## Acceptance criteria

- `AC1` Telegram users can inspect configured ACP agents and switch the current chat to another configured agent without editing config files or restarting nanobot.
- `AC2` Telegram users can inspect and change the effective ACP model for the current chat, and the selected model survives restart/resume through nanobot-owned persistence.
- `AC3` Telegram users can list resumable OpenCode ACP sessions from ACP history and resume one into the current Telegram chat.
- `AC4` Existing non-control slash commands still route to ACP unchanged, and existing local `/new`, `/help`, and `/stop` semantics remain intact.
- `AC5` Telegram command registration and help/status output expose the new local control commands without dropping existing ACP-advertised commands.
- `AC6` Restart/recovery behavior remains correct: after process restart, the selected chat binding still knows which ACP agent, ACP session, and model override to use.
- `AC7` Unattended cron/reminder ACP flows keep their existing agent and permission behavior and do not inherit Telegram-specific control metadata unexpectedly.

## BDD scenarios

- `BDD1` Given two configured ACP agents, when a Telegram user sends `/agent list`, then nanobot returns the configured agent IDs and marks the currently selected one.
- `BDD2` Given ACP mode is active for a Telegram chat, when the user sends `/agent use planner`, then nanobot updates the chat binding to `planner`, clears the old live ACP client for that chat, and acknowledges that a fresh ACP session will be used for the new agent.
- `BDD2A` Given two configured ACP agents with different permission policies or runtime settings, when the user sends `/agent use planner`, then nanobot rebuilds the per-chat ACP client using `planner`'s own `policy`, `env`, `cwd`, and callback wiring instead of reusing the default-agent broker.
- `BDD2B` Given a Telegram chat has a persisted model override for agent `builder`, when the user sends `/agent use planner`, then nanobot clears that override before starting the fresh `planner` session and reports the new effective model based on `planner`'s defaults.
- `BDD3` Given a Telegram chat with an ACP session bound, when the user sends `/model openai/gpt-5.4`, then nanobot calls ACP `session/set_model`, persists the override, and the next prompt runs under that model.
- `BDD3A` Given a Telegram chat has either a persisted model override or only an agent default model, when the user sends bare `/model`, then nanobot returns the current effective model without mutating chat state.
- `BDD4` Given a persisted model override and bound ACP session, when nanobot restarts and the next Telegram prompt resumes the session, then nanobot reapplies the model override before the prompt is sent.
- `BDD4A` Given a Telegram chat with a selected agent and persisted model override, when the user sends `/new` or `/session new`, then nanobot rotates the ACP session id but preserves the selected agent and model override for the next prompt.
- `BDD5` Given ACP history contains resumable sessions for the selected agent, when the user sends `/session list`, then nanobot returns a bounded, Telegram-readable list of ACP session IDs and updated timestamps from ACP history.
- `BDD6` Given `/session list` returned a resumable ACP session ID, when the user sends `/session resume <id>`, then nanobot rebinds the chat to that ACP session and the next message continues in that OpenCode session.
- `BDD7` Given a user sends an unknown slash command such as `/review`, when ACP mode is active, then nanobot still forwards it to ACP unchanged rather than misclassifying it as a local control command.
- `BDD8` Given a Telegram chat in ACP mode, when the user sends `/new`, `/help`, or `/stop`, then the existing nanobot-local semantics still apply exactly as before.
- `BDD9` Given the requested agent ID or ACP session ID is invalid, when the user sends `/agent use missing` or `/session resume missing`, then nanobot returns a clear local error and leaves the existing binding unchanged.
- `BDD10` Given cron or reminder execution uses ACP for unattended work, when interactive Telegram control commands change a Telegram chat binding, then unattended ACP runs continue using their own configured session keys and permission policy path without cross-contamination.

## Phase 1 - Control-command contract and persistence model

### End State

- The tests and service contracts explicitly define nanobot-owned semantics for `/agent`, `/model`, and `/session`, including persisted binding metadata for `agent_id`, `acp_session_id`, and `model_override`, plus ACP-history-backed session listing.

### Tests first

- Extend `tests/acp/test_cli_routing.py` with failing tests for `/agent`, `/model`, and `/session` command interception in ACP mode so partial passthrough implementations cannot falsely pass.
- Add failing tests for invalid command inputs (`/agent use missing`, `/session resume missing`) plus a read-only bare `/model` status path so the command contract cannot drift into setter-only behavior.
- Add or extend ACP store/service tests to prove binding persistence includes a model override and survives reload from disk.
- Add a failing restart/resume regression test proving a persisted model override is reapplied after session reload instead of being lost to backend defaults.
- Add a failing fresh-session regression test proving `/new` and `/session new` preserve the selected agent and model override while replacing only the ACP session id in the binding.
- Add a failing safety test proving an agent switch rebuilds the permission broker and runtime settings from the selected agent definition rather than retaining the prior/default agent wiring.
- Add failing store-level tests in `tests/acp/test_session_store.py` proving ACP history records can persist `metadata["agent_id"]` and binding metadata can round-trip `model_override` without breaking restart/reload behavior.
- Include a guardrail test proving unknown slash commands such as `/review` still route to ACP unchanged.

### Expected files

- `nanobot/acp/store.py`
- `nanobot/acp/sdk_client.py`
- `nanobot/acp/interfaces.py`
- `tests/acp/test_cli_routing.py`
- `tests/acp/test_session_store.py`
- `tests/acp/test_sdk_adapter.py`

### Work

- Lock the binding metadata shape needed for this feature: selected agent, bound ACP session, and optional model override.
- Lock the ACP session-record metadata shape needed for multi-agent history filtering, including persisted `agent_id` ownership for newly written ACP history entries.
- Lock the production history-write path that keeps `ACPFileSessionStore` populated from real ACP session lifecycle events instead of leaving `/session list` dependent on an empty store.
- Define the local control-command parsing contract in tests before changing runtime code.
- Decide and document the bounded `/session list` response shape using only currently available ACP-history evidence sources.
- Keep the contract scoped to ACP/OpenCode history and explicitly exclude nanobot local session history.

### Verify

- `uv run pytest tests/acp/test_cli_routing.py tests/acp/test_sdk_adapter.py`
- `uv run ruff check nanobot/acp/store.py nanobot/acp/interfaces.py tests/acp/test_cli_routing.py tests/acp/test_sdk_adapter.py`

## Phase 2 - ACP service support for agent switching, model overrides, and ACP-history listing

### End State

- `ACPService` can enumerate ACP history sessions, switch the selected ACP agent for a nanobot chat, persist and reapply model overrides, and resume an explicit ACP session ID into the current chat binding.

### Tests first

- Add failing service-level tests proving `switch_agent(...)` updates the binding and clears incompatible live client state.
- Add failing tests proving `set_model_override(...)` persists the override and reapplies it on new/load session paths.
- Add failing tests proving `list_sessions(...)` returns ACP history entries from `ACPFileSessionStore.list_sessions()` filtered/bounded for the selected agent using persisted `ACPSessionRecord.metadata["agent_id"]`, with an explicit fallback policy for legacy records that lack that metadata.
- Add failing tests proving `resume_session(...)` preserves the selected agent, updates the binding to the requested ACP session ID, and uses `load_session(...)` rather than creating a new session.
- Add failing transactional tests proving `resume_session(...)` validates or successfully loads the requested session before persisting the new binding, leaving the prior binding unchanged on invalid or unloadable session IDs.
- Include a failure-path test for agents without `loadSession` capability so resume behavior degrades explicitly instead of silently switching to a fresh session.
- Add a failing service-level safety test proving `switch_agent(...)` rebuilds permission-broker/callback wiring from the selected agent definition instead of the default-agent bootstrap.
- Add failing tests proving agent switches clear any stale `model_override` before creating the first session for the new agent.
- Add failing tests in `tests/acp/test_session_store.py` and `tests/acp/test_sdk_adapter.py` proving real ACP session create/load/prompt paths write and update `ACPSessionRecord` history with `agent_id` metadata.

### Expected files

- `nanobot/acp/service.py`
- `nanobot/acp/sdk_client.py`
- `nanobot/acp/store.py`
- `nanobot/cli/commands.py`
- `tests/acp/test_cli_routing.py`
- `tests/acp/test_session_store.py`
- `tests/acp/test_sdk_adapter.py`

### Work

- Refactor ACP service bootstrap so the runtime can construct clients for multiple configured agents instead of a single baked-in default-agent definition.
- Refactor ACP service bootstrap so the runtime can construct clients for multiple configured agents and derive per-chat permission-broker/runtime settings from the selected agent definition on every create/load/switch path.
- Extend the binding store metadata and accessor helpers to round-trip model overrides and selected agent identity.
- Extend ACP session persistence so newly written `ACPSessionRecord` metadata records the owning `agent_id`; define a deterministic legacy-record fallback for session lists where that metadata is absent.
- Add real ACP-history persistence on the production path by updating `SDKClient` and/or `ACPService` to create and refresh `ACPSessionRecord`s on session create/load and after prompt activity, so `/session list` has live data instead of stale fixtures.
- Add ACP service methods for current binding status, agent switching, model override persistence, ACP-history listing, explicit resume, and fresh-session reset that preserves chat-level control metadata.
- Make `resume_session(...)` transactional: validate/load first, then persist the new binding only after success; if resume fails, leave the prior binding intact.
- Clear any persisted `model_override` when switching agents, and keep override persistence only within the active selected agent.
- Ensure service-level resume and switch operations preserve current permission-broker and callback wiring per selected agent.
- Keep the ACP-history list bounded and deterministic for Telegram output.

### Verify

- `uv run pytest tests/acp/test_cli_routing.py tests/acp/test_sdk_adapter.py -k "agent or model or session"`
- `uv run pytest tests/acp/test_session_store.py tests/acp/test_cli_routing.py tests/acp/test_sdk_adapter.py -k "agent or model or session"`
- `uv run ruff check nanobot/acp/service.py nanobot/acp/sdk_client.py nanobot/acp/store.py nanobot/cli/commands.py tests/acp/test_session_store.py tests/acp/test_cli_routing.py tests/acp/test_sdk_adapter.py`

## Phase 3 - AgentLoop local control-command routing

### End State

- `AgentLoop` intercepts `/agent`, `/model`, and `/session` before ACP passthrough, returns clear local status/error messages, and keeps all existing ACP and non-ACP routing semantics intact.

### Tests first

- Extend `tests/acp/test_cli_routing.py` with failing integration-style tests for `/agent`, `/model`, `/session list`, `/session resume <id>`, and `/session new` routed from Telegram ACP sessions.
- Add guardrail tests proving `/new`, `/help`, and `/stop` still behave exactly as before in ACP mode.
- Add parity tests showing unknown slash commands still hit `_route_to_acp(...)` untouched while control commands are handled locally.
- Add restart/resume tests proving a chat with a persisted binding uses the selected agent and model override on the next routed prompt.
- Add a local-command test proving bare `/model` returns status and does not mutate the persisted model override.
- Add a local-command test proving `/agent use <id>` clears any stale `model_override` and reports the new effective model source for the selected agent.

### Expected files

- `nanobot/agent/loop.py`
- `nanobot/acp/service.py`
- `tests/acp/test_cli_routing.py`

### Work

- Add explicit local parsing for `/agent`, `/model`, and `/session` in ACP mode without regressing current local-command behavior.
- Route local command outcomes through `OutboundMessage` so Telegram gets stable confirmations and errors.
- Keep command parsing intentionally small and deterministic; do not introduce a parallel general-purpose Telegram command framework.
- Preserve the existing ACP fallback/error path for non-control slash commands and plain text prompts.

### Verify

- `uv run pytest tests/acp/test_cli_routing.py`
- `uv run ruff check nanobot/agent/loop.py nanobot/acp/service.py tests/acp/test_cli_routing.py`

## Phase 4 - Telegram menu, help text, and recovery polish

### End State

- Telegram always advertises the local control commands alongside ACP-advertised commands, and the visible help/status text matches the new gateway-owned control semantics.
- Telegram always advertises the local control commands alongside a stable, global ACP-advertised command set built from the deduplicated union of commands across configured agents, and the visible help/status text matches the new gateway-owned control semantics.

### Tests first

- Extend `tests/test_telegram_channel.py` with failing tests proving the Telegram command menu always includes `agent`, `model`, and `session` plus existing local commands and the deduplicated union of ACP-advertised commands across configured agents.
- Add a failing test for command-menu deduplication so a backend-advertised `/model` or `/session` does not cause duplicates.
- Add a failing test for the startup refresh path proving the local control commands remain present even before ACP-advertised commands become available.
- Add a guardrail test for Telegram help/status output if `AgentLoop` help content changes to mention the new local controls.

### Expected files

- `nanobot/channels/telegram.py`
- `nanobot/agent/loop.py`
- `nanobot/acp/service.py`
- `nanobot/cli/commands.py`
- `tests/test_telegram_channel.py`
- `tests/acp/test_cli_routing.py`

### Work

- Extend Telegram's local command catalog with the new gateway-owned controls and keep ACP command registration additive.
- Add or adapt an ACP service discovery method that can enumerate advertised commands across configured agents so Telegram is not forced to guess from the default-agent path.
- Ensure menu registration, startup retry logic, cross-agent command unioning, and deduplication keep the command list stable across restarts.
- Update visible local help text so Telegram users can discover `/agent`, `/model`, and `/session` without relying on ACP backend docs.
- Keep Telegram-specific work thin: no inline-button session browser or custom picker UI in this plan.

### Verify

- `uv run pytest tests/test_telegram_channel.py tests/acp/test_cli_routing.py`
- `uv run ruff check nanobot/channels/telegram.py nanobot/agent/loop.py tests/test_telegram_channel.py tests/acp/test_cli_routing.py`

## Verification strategy

- Phase-owned targeted verifies must pass before moving to the next phase.
- Final repo-truth verification for the completed implementation is:
  - `uv run ruff check .`
  - `uv run pytest`
- If any live OpenCode verification is helpful, keep it opt-in and outside the hermetic default suite.

## Delivery order

- Deliver Phase 1 first to lock semantics and persistence contracts before routing changes.
- Deliver Phase 2 next so service-level capabilities exist before `AgentLoop` starts intercepting the new commands.
- Deliver Phase 3 after service support lands so Telegram users can actually execute the control commands.
- Deliver Phase 4 last to surface the new control plane cleanly in Telegram menus and help output.

## Non-goals

- Building a Telegram inline-button browser for agent/model/session selection.
- Implementing `/model list` or provider-backed model discovery.
- Listing or resuming nanobot local chat-history sessions.
- Automatically resuming the last used session when switching agents in v1.
- Replacing ACP-advertised slash commands with a nanobot-specific shadow command framework.

## Decisions / Deviations Log

- 2026-03-13: Locked `/session` to ACP/OpenCode history only based on user clarification, explicitly excluding nanobot local session history.
- 2026-03-13: Chose nanobot-owned local control commands for `/agent`, `/model`, and `/session` instead of relying on backend-advertised slash commands, because `agent` selection is a gateway concern and model/session durability must survive backend variability.
- 2026-03-13: Resolved review follow-ups by locking bare `/model` as a status command, preserving agent/model controls across fresh-session resets, requiring agent-aware ACP-history metadata for `/session list`, and choosing a deduplicated union of configured-agent ACP commands for the global Telegram menu.
- 2026-03-13: Resolved follow-up review gaps by requiring real ACP-history persistence from production session flows, making `/session resume` transactional, clearing model overrides on agent switch, and adding the existing session-store test module plus multi-agent command discovery work to the owned implementation surface.

## Plan Changelog

- 2026-03-13: Created execution-ready plan for Telegram ACP control commands covering agent selection, model overrides, and ACP-history session resume.
