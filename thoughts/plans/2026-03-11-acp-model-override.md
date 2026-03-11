# ACP Model Override

## Status

- completed

## Goal

- Let nanobot set an explicit ACP session model so OpenCode ACP sessions can avoid broken or unavailable defaults like `opencode/big-pickle`.

## Product intent alignment

- Preserves reliable external-agent delegation by making ACP session behavior deterministic.
- Keeps local-first automation usable when the upstream ACP backend has environment-specific defaults.

## Dependencies

- `thoughts/specs/product_intent.md`
- `thoughts/plans/2026-03-11-acp-timeout-fix.md`

## File ownership

- `nanobot/config/schema.py`
- `nanobot/acp/sdk_client.py`
- `nanobot/acp/service.py`
- `nanobot/cli/commands.py`
- `tests/acp/test_sdk_adapter.py`
- `thoughts/plans/2026-03-11-acp-model-override.md`
- local user config `~/.nanobot/config.json`

## Acceptance criteria

- ACP agent config can declare a preferred session model.
- `SDKClient` can send that model to OpenCode ACP sessions before prompting.
- `SDKClient` can surface assistant text that OpenCode ACP streams through `session/update` notifications.
- Live ACP prompting works with `openai/gpt-5.4` in the current environment.

## BDD scenarios

- Given an ACP agent definition declares `model: "openai/gpt-5.4"`, when nanobot creates an ACP session, then it sets that session model before the first prompt.
- Given a resumed ACP session exists, when nanobot loads it, then it reapplies the configured model so later prompts do not fall back to the broken default.
- Given OpenCode ACP streams assistant text as `agent_message_chunk` updates, when nanobot waits for the model switch to settle and processes the prompt, then it returns those streamed chunks to the caller.
- Given OpenCode ACP is available, when nanobot sends a basic message, then ACP returns assistant text instead of an empty completed turn.

## Progress

- [x] AMO.1 Add config support for ACP session model override
- [x] AMO.2 Teach `SDKClient` and `ACPService` to apply the model override
- [x] AMO.3 Add focused tests for the override flow
- [x] AMO.4 Verify live ACP prompting with `openai/gpt-5.4`

## Resume Instructions (Agent)

- Start with `AMO.1` and keep the change scoped to ACP config and session setup.
- Prefer the smallest additive fix over changing general agent model selection behavior.

## Decisions / Deviations Log

- 2026-03-11: Live debugging showed OpenCode ACP sessions default to `opencode/big-pickle` in this environment, while direct `opencode run` succeeds with `openai/gpt-5.4`. Calling `session/set_model` to `openai/gpt-5.4` before prompting restores streamed assistant text.
- 2026-03-11: Additional probing showed `session/set_model` is not instantly ready for use. Prompting immediately after the model switch returns a zero-token empty turn, but waiting about `0.1s` is sufficient on this machine. Nanobot now applies a brief post-model-switch settle wait before the first prompt.
- 2026-03-11: OpenCode ACP streams assistant text through `session/update` notifications with `sessionUpdate: "agent_message_chunk"` and `content.text`, while the final `session/prompt` result may still contain no inline text. Nanobot now buffers those streamed chunks and returns them from `SDKClient.prompt()`.
- 2026-03-11: `AgentLoop.close_mcp()` now shuts down ACP sessions too, which removes the async-generator cleanup noise seen in the ad-hoc ACP smoke scripts.
- 2026-03-11: The user-facing `nanobot agent --logs` branch had a stale/broken `AgentLoop` initialization path in `nanobot/cli/commands.py` (including an indentation bug that left `agent_loop` undefined). That CLI path now uses the same current `AgentLoop` constructor shape as gateway mode.
- 2026-03-11: Verification results: `uv run pytest tests/acp/test_cli_routing.py tests/acp/test_sdk_adapter.py` passed (`42 passed, 3 skipped`), `uv run ruff check nanobot/cli/commands.py nanobot/agent/loop.py nanobot/acp/sdk_client.py nanobot/acp/sdk_types.py nanobot/acp/service.py tests/acp/test_cli_routing.py tests/acp/test_sdk_adapter.py` passed, and live smoke probes returned `ACP_CLEAN_OK` from `AgentLoop.process_direct(...)` plus `CLI_PATH_OK` from `uv run nanobot agent --logs -m ...`.
- 2026-03-11: Follow-up review caught a real workspace regression: when `acp.agents.<id>.cwd` was unset, ACP sessions used the process launch directory instead of `config.workspace_path`. `ACPServiceConfig` now carries `workspace_dir`, `_get_acp_service()` passes `config.workspace_path`, and `ACPService._create_client()` uses it as the default SDK cwd.
- 2026-03-11: Follow-up review also caught an opt-in real-test drift after `SDKClient.prompt()` switched to `ACPStreamChunk`. `tests/acp/test_acceptance_opencode.py` now checks `chunk.content` instead of dict-style `.get("content")`. Verification: `uv run pytest tests/acp/test_cli_routing.py tests/acp/test_sdk_adapter.py tests/acp/test_acceptance_opencode.py -k "not opencode_real"` passed (`43 passed, 14 deselected`), and `uv run ruff check nanobot/cli/commands.py nanobot/acp/service.py tests/acp/test_cli_routing.py tests/acp/test_acceptance_opencode.py` passed.
