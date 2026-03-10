# ACP-10 Cron Automation

## Status

- ready

## Goal

- Integrate ACP-backed sessions with nanobot's scheduler and unattended task model.

## Product intent alignment

- Advances Outcome 2 by preserving reminders and recurring tasks as a native feature even with ACP delegation.
- Supports Principles 2, 3, and 4.

## Dependencies

- `ACP-00`
- `ACP-02`
- `ACP-03`
- `ACP-06`
- `ACP-08`
- `ACP-09`

## File ownership

- `nanobot/agent/tools/cron.py`
- `nanobot/acp/cron.py`
- `tests/acp/test_cron_acp.py`

## ACP interfaces consumed

- ACP config and session-binding records from `ACP-02`
- runtime session APIs from `ACP-03`
- unattended permission policy model from `ACP-06`
- OpenCode backend registration from `ACP-08`
- ACP-enabled chat routing hooks from `ACP-09`

## Acceptance criteria

- Scheduled jobs can target ACP-backed sessions safely.
- Cron-triggered ACP runs obey unattended permission policy.
- One-shot reminders and recurring ACP tasks can deliver results back to the originating channel.
- Cron integration reuses the existing channel-delivery path and does not take ownership of broad CLI startup wiring.

## BDD scenarios

- Given a recurring ACP task exists, when the cron service fires, then nanobot runs it through the correct backend session or policy-defined isolated session.
- Given a scheduled ACP run needs permission, when no human is present, then unattended policy resolves without hanging.
- Given a cron-triggered run finishes, when delivery is enabled, then the result is posted back to the original channel and chat.

## Progress

- [x] ACP10.1 Add failing cron-plus-ACP tests (14 tests)
- [x] ACP10.2 Wire cron callback path to ACP mode (ACPCronHandler created)
- [x] ACP10.3 Enforce unattended permission rules (policy-driven, no hang)
- [x] ACP10.4 Validate delivery semantics (delivery back to channels)

## Phase 1

### End state

- ACP sessions can be used from reminders and recurring jobs without regressing current cron behavior.

### Tests first

- Add failing tests for one-shot reminder, recurring task, unattended permission path, and delivery back to channels.

### Work

- Preserve current cron behavior for local nanobot sessions.
- Make backend selection explicit and test-covered.
- If a new ACP-specific cron helper module is needed, keep it under `nanobot/acp/` and consume startup hooks from `ACP-09` rather than editing `nanobot/cli/commands.py` directly.

### Verify

- `uv run pytest tests/acp/test_cron_acp.py tests/test_cron_service.py`
- `uv run ruff check nanobot tests/acp`

## Resume Instructions (Agent)

- Do not start broad cron wiring until ACP-backed chat routing exists. Keep changes focused on scheduler integration, not general runtime design.

## Decisions / Deviations Log

- 2026-03-09: Scheduled automation is part of the initial ACP implementation, not a later bolt-on.
