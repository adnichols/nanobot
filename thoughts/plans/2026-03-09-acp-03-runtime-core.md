# ACP-03 Runtime Core

## Status

- ready

## Goal

- Build the core ACP client runtime using the official Python SDK.

## Product intent alignment

- Advances Outcome 1 by making ACP a first-class backend path.
- Supports Principles 1, 3, and 5.

## Dependencies

- `ACP-00`
- `ACP-01`
- consumes storage interfaces from `ACP-02`

## File ownership

- `nanobot/acp/client.py`
- `nanobot/acp/service.py`
- `nanobot/acp/session.py`
- `tests/acp/test_runtime_core.py`

## ACP interfaces consumed

- `ACPSessionStore` from `ACP-02`
- `ACPCallbackRegistry`, `ACPUpdateSink`, and shared request/response types from `ACP-01`

## Acceptance criteria

- Nanobot can initialize an ACP subprocess, record advertised capabilities, create or load a session, prompt it, and cancel an in-flight request.
- Runtime lifecycle handles startup, shutdown, prompt correlation, and baseline reconnect semantics.
- Runtime remains UI-agnostic and does not flatten ACP into the old string-only tool model.
- Runtime exposes importable callback registration hooks for filesystem, terminal, permission, and update-sink handlers through the shared `ACPCallbackRegistry` contract.
- Runtime consumes the shared `ACPSessionStore` contract rather than reaching directly into persistence internals.

## BDD scenarios

- Given `opencode acp` or a fake ACP agent starts successfully, when nanobot initializes, then agent capabilities are captured.
- Given an ACP session exists, when nanobot prompts it, then request/response correlation stays intact through completion.
- Given cancellation is requested mid-turn, when the runtime sends `session/cancel`, then prompt state transitions cleanly without corrupting session state.
- Given a stored ACP session binding exists, when the runtime starts and the backend supports load-session, then session recovery reuses the saved binding.
- Given the ACP backend process exits unexpectedly, when the next prompt arrives, then the runtime reconnects or surfaces a deterministic failure without corrupting stored state.
- Given multiple ACP sessions are active, when prompts and updates overlap, then state remains isolated by session and request correlation ids.
- Given an ACP backend cannot be started or initialized, when startup is attempted, then the runtime returns a testable failure that later routing tracks can handle.

## Progress

- [x] ACP03.1 Implement connection bootstrap
- [x] ACP03.2 Implement session lifecycle methods
- [x] ACP03.3 Implement prompt and cancel flow
- [x] ACP03.4 Add runtime tests against fake agent fixtures

## Phase 1

### End state

- Core ACP runtime works against fakes and exposes clean interfaces to later tracks.

### Tests first

- Add failing tests for initialize, new-session, load-session, prompt, cancel, and runtime shutdown behavior.

### Work

- Use ACP SDK helpers where they reduce custom protocol handling.
- Keep rendering, permissions, filesystem, and terminal behavior out of this track except for callback registration hooks.
- Define the runtime-facing methods on the callback registry explicitly enough that `ACP-04`, `ACP-05`, `ACP-06`, and `ACP-07` can implement against them without local invention.

### Verify

- `uv run pytest tests/acp/test_runtime_core.py`
- `uv run ruff check nanobot/acp tests/acp`

## Resume Instructions (Agent)

- Treat this plan as the transport and lifecycle owner. Other tracks should integrate through its public interfaces rather than patching protocol flow directly.

## Decisions / Deviations Log

- 2026-03-09: This track intentionally excludes user-visible rendering and permission UX.
