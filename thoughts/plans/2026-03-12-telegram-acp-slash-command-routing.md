# Telegram ACP Slash Command Routing

## Status

- complete

## Goal

- Make Telegram a first-class ACP control surface for OpenCode slash commands, with trusted single-user sessions defaulting to approval-free execution while preserving resumable sessions, channel-native progress, and a future approval path.

## Why this plan exists

- `nanobot` already has most of the ACP backbone, but Telegram currently drops most slash commands before they reach `AgentLoop` or `ACPService`.
- The user wants Telegram to be the main control plane for OpenCode work, including slash-command-driven flows, without depending on a direct Telegram-to-OpenCode architecture.
- ACP session reset, metadata preservation, and update visibility still have integration gaps that would make Telegram feel unreliable even if commands were forwarded.
- ACP permission and callback handling is not fully round-tripped back to the agent today, so some OpenCode actions will still stall unless that runtime gap is closed.

## Authority and inputs

- `AGENTS.md`
- `thoughts/plans/AGENTS.md`
- `thoughts/specs/product_intent.md`
- User clarification on 2026-03-12: avoid permission prompts by default for current single-user Telegram usage, but keep the pieces needed for approvals so prompts can be enabled later if required.
- Validated implementation surfaces: `nanobot/channels/telegram.py`, `nanobot/agent/loop.py`, `nanobot/cli/commands.py`, `nanobot/acp/service.py`, `nanobot/acp/sdk_client.py`, `nanobot/acp/permissions.py`, `nanobot/acp/policy.py`, `tests/acp/test_cli_routing.py`, `tests/acp/test_sdk_adapter.py`, `tests/acp/test_cron_acp.py`.

## Dependencies

- `thoughts/plans/2026-03-09-acp-02-config-and-session-store.md`
- `thoughts/plans/2026-03-09-acp-03-runtime-core.md`
- `thoughts/plans/2026-03-09-acp-06-permission-broker.md`
- `thoughts/plans/2026-03-09-acp-07-update-bridge-and-rendering.md`
- `thoughts/plans/2026-03-09-acp-08-opencode-and-mcp.md`
- `thoughts/plans/2026-03-09-acp-09-cli-and-chat-routing.md`

## File ownership

- `nanobot/channels/telegram.py`
- `nanobot/agent/loop.py`
- `nanobot/cli/commands.py`
- `nanobot/acp/service.py`
- `nanobot/acp/sdk_client.py`
- `nanobot/acp/permissions.py`
- `nanobot/acp/fs.py`
- `nanobot/acp/terminal.py`
- `tests/test_telegram_channel.py`
- `tests/acp/test_cli_routing.py`
- `tests/acp/test_sdk_adapter.py`
- `tests/acp/test_cron_acp.py`

## ACP interfaces consumed

- `ACPService.load_session()`, `ACPService.process_message()`, `ACPService.cancel_operation()`, `ACPService.subscribe_updates()`, `ACPService.shutdown_session()`
- `ACPSessionBindingStore.delete_binding()` via the service-owned binding store path
- `ACPCallbackRegistry`
- `ACPUpdateSink`
- `ACPUpdateAccumulator` and `ACPProgressVisibility`
- `ACPPermissionBroker` and `PermissionBrokerFactory`
- `ACPPermissionRequest`, `ACPPermissionDecision`, `ACPFilesystemCallback`, and `ACPTerminalCallback`

## Current implementation reality

- `TelegramChannel` only registers `/start`, `/new`, and `/help`; its main text handler excludes `filters.COMMAND`, so arbitrary slash commands never reach the bus. `BOT_COMMANDS` advertises `/stop`, but Telegram does not currently forward it.
- `_forward_command()` currently forwards raw command text from Telegram, which means group-chat forms like `/model@botname` are not normalized before local or ACP routing.
- `_forward_command()` also drops the normal Telegram metadata payload (`message_id`, `user_id`, `username`, `first_name`, `is_group`) that `_on_message()` includes, so slash-command ingress currently does not carry the same metadata shape into the bus.
- `AgentLoop` already routes ACP sessions through `_route_to_acp()`, preserves the `telegram:<chat_id>` session key shape, and keeps `/new` and `/help` local, so the main integration seam already exists.
- `AgentLoop` currently returns ACP final responses without inbound Telegram metadata, which breaks reply-quoting behavior when `reply_to_message` is enabled.
- `AgentLoop` only subscribes to ACP updates when `channels.acp_stream_content` is enabled, even though separate visibility flags already exist for thinking, tool calls, tool results, and system notices.
- `ACPService.shutdown_session()` only drops the live client; it does not clear the persisted ACP binding, so `/new` does not guarantee a fresh OpenCode session.
- Existing config surfaces already cover most of what this feature needs: `ACPAgentDefinition.policy`, `ACPConfig.permission_policies`, Telegram `reply_to_message`, and channel ACP visibility flags. No new schema is required unless current wiring proves insufficient.
- `ACPService._create_client()` threads `callback_registry` into `SDKClient`, but it does not currently thread a permission broker, so interactive or trusted-session permission behavior cannot yet be configured end-to-end.
- `SDKNotificationHandler` emits permission-related update events and can ask an `ACPPermissionBroker` for a decision, but it does not currently send permission, filesystem, or terminal decisions back to the ACP agent. That is the main blocker for truly arbitrary Telegram-driven OpenCode commands.
- `tests/acp/test_sdk_adapter.py` already proves the ACP connection wrapper can call `send_notification()`, so callback round-trip work can target real SDK behavior rather than inventing a new transport abstraction.
- Filesystem and terminal callback surfaces already exist in `nanobot/acp/fs.py` and `nanobot/acp/terminal.py`, and `ACPService` exposes registration hooks, but startup wiring does not yet attach those handlers to the live ACP service path.
- Reuse and dependency decision:
- Reuse in-repo surfaces: `TelegramChannel`, `BaseChannel._handle_message()`, `AgentLoop`, `ACPService`, `ACPSessionBindingStore`, `ACPPermissionBroker`, `PermissionBrokerFactory`, and ACP update visibility primitives.
- Reuse stdlib/platform primitives: simple string normalization for `/command@botname`, existing `python-telegram-bot` handler ordering, and existing asyncio callback plumbing.
- `python-telegram-bot` command handlers help route command updates, but they do not rewrite `update.message.text` into a normalized `/command args` string for bus delivery. Custom normalization remains the smallest adapter that preserves current nanobot bus semantics.
- External components considered: direct reuse of `opencode-telegram` was rejected because the user only wants it as UX reference for slash-command support, not as architecture or dependency. No new external dependency is approved or needed for this plan.
- Chosen approach: adapt existing nanobot Telegram and ACP surfaces, keep Telegram thin, and finish the ACP runtime gaps instead of introducing a parallel Telegram-specific command subsystem.

## Progress

- [x] TGACPR.1 Strengthen the Telegram slash-routing contract and tests.
- [x] TGACPR.2 Fix ACP routing, metadata, and fresh-session reset semantics.
- [x] TGACPR.3 Wire trusted interactive permission defaults and progress visibility.
- [x] TGACPR.4 Complete ACP permission, filesystem, and terminal callback round-trips.

## Resume Instructions (Agent)

- Read this plan fully before editing code.
- Confirm the owned file set before starting and do not drift outside it unless a logged deviation becomes necessary.
- This plan is complete; there is no unchecked progress item to resume.
- If new Telegram ACP routing issues appear, use this file as the execution record and create a follow-up plan instead of reopening scope implicitly.
- Execute one phase at a time using a tests-first loop, then run the phase verify commands, then perform a review/fix pass before moving to the next phase.
- Keep cron and unattended ACP behavior stable while changing interactive Telegram routing.
- Ask the user only if implementation reveals that existing ACP policy surfaces cannot express the trusted-single-user default without a schema change.

## Product intent alignment

- Advances Outcome 1 by making ACP-backed OpenCode sessions reachable through Telegram, the user's primary control surface.
- Preserves Outcome 2 by keeping unattended cron and reminder policy behavior unchanged while improving interactive chat routing.
- Advances Outcome 3 by extending existing ACP integration instead of coupling Telegram to a one-off direct OpenCode implementation.
- Supports Principle 2 by treating Telegram as a first-class channel rather than a reduced ACP subset.
- Supports Principle 3 by making slash commands, session reset, progress visibility, and callback completion feel native and resumable from Telegram.
- Supports Principle 4 by keeping unattended automation policy-driven and by confining permissive defaults to trusted interactive Telegram sessions only.
- Supports Principle 5 by reusing explicit ACP config surfaces instead of adding hidden Telegram-only behavior or provider-specific assumptions.

## Locked decisions

- Telegram remains a thin pass-through surface for OpenCode slash commands; do not add a Telegram-specific OpenCode wrapper command catalog in this plan.
- `/start` and `/help` remain Telegram-local commands. `/new` and `/stop` are forwarded to the bus so existing nanobot command handling in `AgentLoop` can process them locally; they are not passed through to OpenCode.
- Unknown slash commands are forwarded to the bus and then routed to ACP exactly like normal message content.
- Group command forms such as `/command@botname args` are normalized before local-command matching and ACP forwarding.
- Trusted interactive Telegram ACP sessions default to no approval prompts. Approval plumbing remains present so `ask` and `deny` policies can be used later without redesign.
- Cron and other unattended ACP flows must keep their current policy-driven safety posture and must not inherit Telegram's permissive default.
- Preserve inbound Telegram metadata on final ACP responses so reply threading and channel-native behavior survive the ACP hop.
- In ACP mode, `/stop` means cancel the in-flight ACP operation for the current session via nanobot's existing local stop path; it does not reset the session binding or become an OpenCode slash command.
- `ACPAgentDefinition.policy="auto"` maps to a trusted interactive broker choice for Telegram sessions: resolve without prompting by default, while explicit `ask` and `deny` continue to map to stricter broker behavior. Unattended sessions continue using `UnattendedPermissionPolicy`.
- Prefer existing config and policy surfaces over schema expansion. If a schema change becomes unavoidable, stop after the failing tests and log the reason before broadening scope.
- Do not introduce any new external dependency. User approval for new dependency: not granted and not needed.

## Acceptance criteria

- `AC1` Telegram forwards arbitrary OpenCode slash commands into the normal nanobot bus and ACP path, including group-chat `/command@botname` syntax.
- `AC2` Nanobot-local Telegram commands keep their intended semantics: `/start` and `/help` remain local, `/new` starts a fresh nanobot-managed session path, and `/stop` cancels the in-flight ACP operation without being passed through to OpenCode.
- `AC3` ACP-backed Telegram replies preserve the inbound `message_id` metadata needed for reply quoting, and ACP progress, thinking, tool, and system updates can be surfaced when their existing visibility flags are enabled even if live content streaming is disabled.
- `AC4` ACP `/new` reliably produces a fresh backend session on the next Telegram prompt instead of resuming the previous persisted binding.
- `AC5` Trusted Telegram ACP sessions avoid approval prompts by default while keeping `ask` and `deny` capable for future use and leaving unattended cron policy behavior unchanged.
- `AC6` ACP permission, filesystem, and terminal callback decisions are sent back to the ACP agent so command execution can complete instead of stalling.
- `AC7` Telegram's native command menu reflects the available local and ACP-advertised slash commands, and startup retry behavior prevents the menu from getting stuck on a local-only baseline when ACP command discovery lags service boot.

## BDD scenarios

- `BDD1` Given ACP is configured for Telegram, when the user sends `/model openai/gpt-5.4` in a Telegram DM, then `TelegramChannel` forwards the command through the bus and `ACPService.process_message()` receives the same command under session key `telegram:<chat_id>`.
- `BDD2` Given a Telegram group message `/init@nanobot repo`, when the command is handled, then nanobot normalizes it to `/init repo` before local-command matching and ACP routing.
- `BDD3` Given ACP mode is active, when the user sends `/new` or `/stop`, then nanobot handles those commands locally and does not forward them to OpenCode.
- `BDD4` Given `reply_to_message` is enabled and the user starts a fresh ACP conversation with `/new`, when the next Telegram prompt completes, then the final outbound message still carries the inbound `message_id` metadata needed for reply quoting and does not reuse the old ACP session binding.
- `BDD5` Given a trusted Telegram interactive session using the default policy, when OpenCode requests filesystem or terminal permission, then nanobot resolves it without prompting and the ACP prompt continues.
- `BDD6` Given the operator later configures `ask`, when ACP raises a permission request, then request and decision updates are emitted through the existing ACP update path and the chosen decision is sent back to the agent.
- `BDD7` Given a cron-triggered ACP session with a restrictive unattended policy, when ACP requests permission, then the existing unattended policy still decides the request and the Telegram interactive default does not weaken cron safety.
- `BDD8` Given the ACP agent is unavailable for a Telegram session, when the user sends a slash command, then nanobot returns the existing ACP failure path for that session instead of swallowing the command at the Telegram layer.
- `BDD9` Given a malformed group command that normalizes to an empty or non-command string, when Telegram processes it, then nanobot handles it predictably without routing an invalid slash command into ACP.
- `BDD10` Given the same OpenCode slash command is sent through CLI and Telegram ACP entrypoints, when both reach `ACPService.process_message()`, then they preserve the same command text while keeping channel-specific session keys and metadata behavior.

## Phase 1 - Telegram slash-routing contract

### End State

- `TelegramChannel` no longer drops unknown slash commands before they reach the nanobot bus, forwards `/new` and `/stop` into nanobot's local command path via `_handle_message()`, normalizes `/command@botname`, preserves the same Telegram metadata shape that `_on_message()` sends, and keeps the existing non-command media and text flow.

### Tests first

- Add `tests/test_telegram_channel.py` as a new focused channel test module.
- Start with failing tests for unknown slash command forwarding, `/stop` forwarding to the bus for local `AgentLoop` handling, `/command@botname arg` normalization, `/start` local handling, and `/help` local handling.
- Add a failing test proving slash-command forwarding includes the same Telegram metadata fields (`message_id`, `user_id`, `username`, `first_name`, `is_group`) that ordinary message ingress publishes.
- Include a guardrail test that plain text still routes through `_on_message()` so the command pass-through change does not break non-command chat behavior.
- Include a failure-path test for malformed or empty normalized group commands so the Telegram layer does not emit invalid slash content.
- Include a guardrail test for group-chat commands explicitly addressed to a different bot (for example `/init@otherbot`) so nanobot does not hijack commands that were not meant for it.
- Add a failing startup-registration test proving Telegram command-menu sync includes ACP-advertised commands and retries when ACP command discovery is not ready on the first boot attempt.

### Expected files

- `nanobot/channels/telegram.py`
- `tests/test_telegram_channel.py`

### Work

- Adjust Telegram handler registration so explicit local commands run first and a generic command-forwarding path handles everything else.
- Normalize Telegram bot-mention command syntax before publishing to the bus.
- Preserve the same Telegram metadata payload shape for command ingress that `_on_message()` currently produces for normal text messages.
- Ignore group-chat commands addressed to a different bot username while preserving normalization for commands addressed to nanobot.
- Register Telegram native command-menu entries from ACP-advertised slash commands and add startup retry logic so delayed ACP discovery does not leave the menu stale after service restart.
- Keep Telegram thin: do not add OpenCode-specific command parsing or Telegram-only business logic beyond normalization and handler routing.
- Preserve existing ACL, sender ID, typing indicator, and media behavior.

### Verify

- `uv run pytest tests/test_telegram_channel.py`
- `uv run ruff check nanobot/channels/telegram.py tests/test_telegram_channel.py`

## Phase 2 - ACP routing, metadata, and fresh-session reset

### End State

- ACP-backed Telegram sessions keep the inbound `message_id` metadata needed for reply quoting, subscribe to ACP updates whenever any existing ACP visibility category is enabled, and use a service path that clears the persisted binding so `/new` cannot silently resume the old OpenCode session.

### Tests first

- Extend `tests/acp/test_cli_routing.py` with failing tests for preserving Telegram `message_id` metadata on ACP responses so reply quoting still works.
- Add a failing test proving ACP updates are subscribed when `acp_show_tool_calls`, `acp_show_tool_results`, `acp_show_thinking`, or `acp_show_system` is enabled even when `acp_stream_content` is false.
- Add a failing restart/resume regression test showing that `/new` must delete the existing ACP binding from `ACPSessionBindingStore`, not only remove the live client, before the next prompt creates a fresh session.
- Keep a guardrail assertion for `/stop` local cancellation behavior so command-forwarding changes do not regress existing stop semantics.
- Add a parity-oriented failure-path test showing ACP routing errors still surface through the current ACP failure path when the inbound Telegram content is a slash command.
- Add a failing reuse-session regression test proving ACP update subscriptions are cleared or rebound between prompts so progress updates cannot leak into the wrong Telegram callback when the same ACP session is reused.

### Expected files

- `nanobot/agent/loop.py`
- `nanobot/acp/service.py`
- `tests/acp/test_cli_routing.py`

### Work

- Preserve inbound `InboundMessage.metadata` on the final `OutboundMessage` returned from ACP routing.
- Split update subscription logic from the `acp_stream_content` flag so other ACP visibility categories can be surfaced independently.
- Add or adapt a fresh-session reset path in `ACPService` that clears both the live client and the persisted binding for a session key.
- Clear stale ACP update sinks whenever a prompt path does not attach a new visible-progress sink, and rebind the sink explicitly when progress visibility is enabled on a reused ACP session.
- Keep existing local fallback and session-key behavior intact.

### Verify

- `uv run pytest tests/acp/test_cli_routing.py`
- `uv run ruff check nanobot/agent/loop.py nanobot/acp/service.py tests/acp/test_cli_routing.py`

## Phase 3 - Trusted interactive permission defaults and visibility wiring

### End State

- Startup wiring creates ACP permission broker behavior from existing config surfaces so trusted interactive Telegram sessions resolve `auto` without prompting, explicit `ask` and `deny` remain possible, and unattended cron flows keep their current policy-driven handling with a clear interactive-versus-unattended boundary.

### Tests first

- Extend `tests/acp/test_cli_routing.py` with a failing integration test proving interactive Telegram ACP sessions do not prompt under the default trusted policy.
- Extend `tests/acp/test_cron_acp.py` with a guardrail test proving unattended ACP sessions still honor their configured allow or deny behavior after interactive policy wiring changes and that the interaction mode boundary remains explicit.
- Add a failing unit or integration test showing that explicit `ask` mode still emits permission request and decision updates through the ACP update path, and define the current expected outcome as timeout or denial until a channel-specific approval responder is implemented.

### Expected files

- `nanobot/cli/commands.py`
- `nanobot/acp/service.py`
- `nanobot/acp/permissions.py`
- `tests/acp/test_cli_routing.py`
- `tests/acp/test_cron_acp.py`

### Work

- Define and implement the runtime meaning of `ACPAgentDefinition.policy="auto"` for trusted interactive Telegram sessions without changing schema shape.
- Reuse `PermissionBrokerFactory` and the existing unattended policy model instead of introducing a Telegram-only permission system.
- Ensure the permission broker and callback registry are actually threaded through live ACP service creation; close the current gap where `ACPService` passes a callback registry but not a broker into `SDKClient`.
- Make the trusted-session selection explicit at runtime: Telegram chat sessions (`telegram:` session keys / interactive gateway path) receive the trusted interactive broker choice, while cron and other unattended entrypoints continue to receive unattended brokers and policies.
- Keep the path to future `ask`-mode approvals intact without forcing prompts for the current single-user Telegram workflow.
- Document in code and tests that `interactive=True` is the discriminant for trusted Telegram sessions while cron and other unattended paths continue to use `interactive=False` plus `UnattendedPermissionPolicy`.

### Verify

- `uv run pytest tests/acp/test_cli_routing.py tests/acp/test_cron_acp.py`
- `uv run ruff check nanobot/cli/commands.py nanobot/acp/service.py nanobot/acp/permissions.py tests/acp/test_cli_routing.py tests/acp/test_cron_acp.py`

## Phase 4 - ACP callback round-trip completion

### End State

- ACP callback-driven OpenCode actions complete end-to-end instead of stalling inside the SDK adapter: `SDKNotificationHandler` sends permission, filesystem, and terminal decisions back to the ACP agent over the existing connection `send_notification()` path, preserves update emissions for observability, and proves the callback path with hermetic tests.

### Tests first

- Extend `tests/acp/test_sdk_adapter.py` with failing tests for permission decisions being returned over the SDK connection.
- Add failing tests for filesystem and terminal callback decisions being returned to the agent, not just logged locally.
- Include a denial-path test so the callback round-trip covers both allowed and denied outcomes and ensures decision updates still surface.
- Add a failing integration-oriented test showing the live ACP service path registers real filesystem and terminal handlers before slash-command-driven OpenCode work reaches the SDK adapter.
- Add a failing policy-enforcement test proving live filesystem and terminal callback wiring still respects `ask` and `deny` policy outcomes after the real handlers are attached.

### Expected files

- `nanobot/cli/commands.py`
- `nanobot/acp/service.py`
- `nanobot/acp/sdk_client.py`
- `nanobot/acp/fs.py`
- `nanobot/acp/terminal.py`
- `tests/acp/test_sdk_adapter.py`
- `tests/acp/test_cli_routing.py`

### Work

- Implement the real ACP response path for permission, filesystem, and terminal callbacks using the SDK connection API rather than log-only placeholders.
- Attach the existing filesystem and terminal handler surfaces to the live ACP startup/service path so Telegram-driven OpenCode sessions hit real handlers instead of adapter-only test doubles.
- Keep payload conversion aligned with existing ACP normalization helpers and update-event shapes.
- Avoid introducing a live OpenCode dependency into the default test suite; use fakes or mocked connection objects for RED and GREEN verification.
- Preserve denial-path behavior and update emission semantics so stricter policies remain observable once callback responses are wired.
- Verify that the live-handler path cannot bypass `ask` or `deny` decisions after callback round-trips are enabled.

### Verify

- `uv run pytest tests/acp/test_sdk_adapter.py tests/acp/test_cli_routing.py tests/test_telegram_channel.py`
- `uv run ruff check nanobot/cli/commands.py nanobot/acp/service.py nanobot/acp/sdk_client.py nanobot/acp/fs.py nanobot/acp/terminal.py tests/acp/test_sdk_adapter.py tests/acp/test_cli_routing.py tests/test_telegram_channel.py`

## Verification strategy

- Run the narrow phase-specific verify commands after each phase before moving on.
- After all phases complete, run the canonical repo gates in order:
  - `uv run ruff check .`
  - `uv run pytest`
- Optional manual acceptance only if needed and explicitly opted in: `NANOBOT_TEST_OPENCODE=1 uv run pytest tests/acp/test_acceptance_opencode.py -v -m opencode_real`

## Delivery order

- Deliver Phase 1 first so Telegram can express the target command contract in tests.
- Deliver Phase 2 next so ACP responses and fresh-session semantics are correct before policy work broadens the runtime path.
- Deliver Phase 3 before Phase 4 so the runtime is wired to the correct trusted-session policy model when callback completion lands.
- Deliver Phase 4 last, then run repo-wide gates and a review/fix loop until no substantive issues remain.

## Non-goals

- Do not add Telegram inline keyboards, Telegram-specific OpenCode wrappers, or a new command catalogue in this plan.
- Do not modify `.env` files, Telegram tokens, local user config, or external service credentials.
- Do not adopt or vendor `opencode-telegram`; it is reference material only.
- Do not add new build or e2e commands to repo truth.
- Do not redesign multi-user authorization; this plan is scoped to the current trusted single-user Telegram workflow plus future-compatible approval hooks.

## Decisions / Deviations Log

- 2026-03-12: The user wants Telegram slash-command support over ACP with no approval prompts by default for current single-user usage; approval-capable plumbing remains in scope so stricter policy can be enabled later.
- 2026-03-12: `opencode-telegram` is treated only as a reference for `/command` support UX and is not approved as a dependency, architecture template, or copied subsystem.
- 2026-03-12: Phase 1 command normalization was tightened to preserve multiline slash-command arguments and ignore Telegram group commands explicitly addressed to a different bot username while still forwarding `/new`, `/stop`, and unknown commands through nanobot's local bus path.
- 2026-03-12: Phase 2 introduced an explicit `ACPService.reset_session()` path so ACP-mode `/new` clears persisted bindings as well as live clients, while normal `shutdown_session()` keeps restart/resume semantics for ordinary shutdown and active-client reuse remains intact.
- 2026-03-12: Phase 3 made trusted interactive `auto` approval-free only for `telegram:` sessions, kept non-Telegram and unattended sessions policy-driven, and threaded a shared callback registry into both permission-broker creation and future ACP clients so later `ask` flows can use registered handlers instead of hard-denying by construction.
- 2026-03-12: Phase 4 bound live filesystem and terminal handler objects into `ACPService` client creation, and `SDKNotificationHandler` now returns callback decisions over the active SDK connection while preserving permission decision updates for observability.
- 2026-03-12: Phase 4 review hardening advertised ACP filesystem and terminal client capabilities, routed direct filesystem and terminal callbacks through permission enforcement, separated live execution-handler wiring from approval callbacks, and fixed denial/error branches so `ask`/`deny` policies cannot be bypassed or crash on rejected callback paths.
- 2026-03-12: Post-review hardening clears stale ACP update sinks between prompts so reused sessions cannot leak progress into the wrong channel callback, and terminal lifecycle callback failures now map to structured protocol errors instead of surfacing as internal SDK exceptions.
- 2026-03-12: Telegram command registration now probes ACP `available_commands_update` data and merges valid advertised slash commands into the native Telegram command menu, because forwarding unknown slash commands alone left users stuck on the original static `/start` `/new` `/stop` `/help` catalog.
- 2026-03-12: Telegram startup now retries command registration after boot when ACP slash commands are not ready on the first pass, because Homebrew service restarts could connect to Telegram before ACP command discovery settled and leave the bot menu stuck on the local-only baseline.

## Plan Changelog

- 2026-03-12: Created initial execution-ready plan for Telegram ACP slash-command routing, trusted-session permission defaults, and ACP callback completion.
- 2026-03-12: Revised the plan after review to resolve `/stop` semantics, dependency references, stable progress IDs, policy mapping detail, and phase-level execution ambiguities.
- 2026-03-12: Revised the plan again after follow-up review to require Telegram slash-command metadata parity and real filesystem/terminal handler wiring on the live ACP path.
- 2026-03-12: Captured post-review regression fixes for stale ACP update subscriptions and terminal lifecycle protocol error translation.
