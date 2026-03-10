# ACP-07 Update Bridge And Rendering

## Status

- ready

## Goal

- Convert streamed ACP updates into nanobot bus events and user-visible progress.

## Product intent alignment

- Advances Outcome 1 by making ACP sessions feel native in nanobot channels.
- Supports Principles 2 and 3.

## Dependencies

- `ACP-00`
- `ACP-01`
- integrates with update hooks from `ACP-03`
- consumes permission-state outputs from `ACP-06`

## File ownership

- `nanobot/acp/updates.py`
- `nanobot/acp/render.py`
- `tests/acp/test_update_rendering.py`

## ACP interfaces consumed

- `ACPUpdateEvent` and update-sink registration from `ACP-01` and `ACP-03`
- permission request and decision events from `ACP-01` and `ACP-06`

## Acceptance criteria

- `session/update` notifications are accumulated and rendered into channel-safe progress messages.
- Tool updates, plan updates, message chunks, and completion state remain visible without flattening away important semantics.
- Rendering suppresses noisy duplicates and preserves a coherent final answer.
- Duplicate suppression is deterministic: identical rendered progress payloads for the same session and prompt correlation id are emitted at most once.

## BDD scenarios

- Given an ACP agent streams tool progress, when nanobot receives updates, then the user sees sensible incremental progress.
- Given the final answer arrives after many chunks, when rendering completes, then the user receives one coherent completion message.
- Given redundant or repeated updates arrive, when rendering runs, then duplicate outbound spam is suppressed.

## Progress

- [x] ACP07.1 Add failing rendering tests
- [x] ACP07.2 Integrate session update accumulation (ACPUpdateAccumulator)
- [x] ACP07.3 Implement outbound event rendering (ACPRenderer with OutboundMessage)
- [x] ACP07.4 Tune duplicate suppression and completion behavior (SHA256 hash-based, 9 tests passing)

## Phase 1

### End state

- ACP progress and completion updates reach the nanobot message bus cleanly.

### Tests first

- Add failing tests for tool update rendering, chunk accumulation, final answer emission, and duplicate suppression.

### Work

- Reuse nanobot's existing outbound message path by publishing `OutboundMessage` events onto the message bus rather than inventing a parallel transport.
- Keep chat binding and CLI startup out of scope.

### Verify

- `uv run pytest tests/acp/test_update_rendering.py`
- `uv run ruff check nanobot/acp tests/acp`

## Resume Instructions (Agent)

- Own the translation from raw ACP updates to nanobot-visible progress events. Do not patch the runtime transport directly unless the shared update hook is broken.

## Decisions / Deviations Log

- 2026-03-09: This plan owns user-visible ACP progress semantics so later routing work can stay thin.
