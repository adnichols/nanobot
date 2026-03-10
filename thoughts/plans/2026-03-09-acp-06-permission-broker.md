# ACP-06 Permission Broker

## Status

- ready

## Goal

- Implement ACP permission handling for both interactive chats and unattended automation.

## Product intent alignment

- Advances Outcome 2 by making scheduled ACP runs safe and non-blocking.
- Advances Outcome 3 by keeping backend delegation trustworthy.
- Supports Principles 3 and 4.

## Dependencies

- `ACP-00`
- `ACP-01`
- integrates with permission callback registration from `ACP-03`

## File ownership

- `nanobot/acp/permissions.py`
- `nanobot/acp/policy.py`
- `tests/acp/test_permission_broker.py`

## ACP interfaces consumed

- `ACPPermissionHandler` registration hooks from `ACP-01` and `ACP-03`
- shared permission request/decision event types from `ACP-01`

## Acceptance criteria

- ACP permission requests can be allowed, denied, or timed out.
- Non-interactive automation mode is policy-driven and cannot hang indefinitely.
- Correlation state remains correct across overlapping requests.
- `nanobot/acp/policy.py` defines the importable unattended permission policy model consumed by `ACP-09` and `ACP-10`, including default mode and per-action overrides.

## BDD scenarios

- Given a risky tool request arrives in an interactive chat, when the user approves, then the broker returns allow with the correct correlation id.
- Given a cron-triggered ACP session runs unattended, when a permission request arrives, then the configured automation policy resolves it without deadlock.
- Given multiple permission requests overlap, when replies arrive out of order, then they still map to the correct requests.

## Progress

- [x] ACP06.1 Add failing permission tests
- [x] ACP06.2 Implement broker state machine (allow, deny, timeout, concurrent correlation)
- [x] ACP06.3 Add interactive vs unattended policy handling (UnattendedPermissionPolicy model)
- [x] ACP06.4 Publish event contract for routing and rendering tracks (20 tests passing)

## Phase 1

### End state

- Permission flow is correct, test-covered, and safe for unattended scheduled execution.

### Tests first

- Add failing tests for allow, deny, timeout, unattended resolution, and concurrent correlation.

### Work

- Use ACP SDK helpers if they reduce custom request bookkeeping.
- Keep UI text and rendering out of scope for this plan.
- Keep the policy model small and deterministic: explicit default behavior plus override rules keyed by ACP action or tool identity.

### Verify

- `uv run pytest tests/acp/test_permission_broker.py`
- `uv run ruff check nanobot/acp tests/acp`

## Resume Instructions (Agent)

- Keep the broker UI-agnostic. Channel-specific prompts and rendering belong to later integration tracks.

## Decisions / Deviations Log

- 2026-03-09: Unattended cron behavior is a first-class requirement, not a later hardening task.
- 2026-03-09: The unattended permission policy is owned here so cron and routing tracks can import one concrete model.
