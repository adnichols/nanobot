# ACP-01 Contracts And Fakes

## Status

- ready

## Goal

- Define ACP contracts, fake runtimes, and failing tests that every later ACP track builds against.

## Product intent alignment

- Advances Outcome 1 by giving ACP a stable first-class integration surface.
- Advances Outcome 3 by keeping external backend support modular and provider-agnostic.
- Supports Principles 1, 3, and 5.

## Dependencies

- `ACP-00`

## File ownership

- `nanobot/acp/types.py`
- `nanobot/acp/contracts.py`
- `nanobot/acp/interfaces.py`
- `tests/acp/conftest.py`
- `tests/acp/fakes/`
- `tests/acp/test_contracts.py`
- `tests/acp/test_fake_agent_protocol.py`

## ACP interfaces consumed

- none; this track defines the shared interface surface for later tracks

## Acceptance criteria

- Shared ACP-facing types exist for runtime, session records, permission requests, filesystem callbacks, terminal callbacks, update events, and rendered updates.
- Importable interfaces exist for:
  - `ACPSessionStore`
  - `ACPCallbackRegistry`
  - `ACPUpdateSink`
  - `ACPRenderEvent`
  - permission decision and request records used by downstream tracks
- Fake ACP agent fixtures can simulate initialize, prompt, session updates, permission requests, cancel, and load-session flows.
- Downstream tracks can import a single shared contract layer instead of inventing interfaces locally.
- Contract publication happens through importable Python modules, not prose-only notes.

## BDD scenarios

- Given a fake ACP agent emits streamed updates, when nanobot consumes them, then the shared contract can represent them losslessly.
- Given a permission request is emitted, when the fake broker responds, then the contract preserves correlation IDs and outcomes.
- Given a saved session is reloaded, when the fake agent supports load-session, then the contract exposes the state needed for resume.
- Given a downstream track imports callback, storage, and update interfaces, when it loads a synthetic consumer module, then the contracts import without reaching into implementation files.

## Progress

- [x] ACP01.1 Define shared ACP types and interfaces
- [x] ACP01.2 Add fake ACP agent harness and fixtures
- [x] ACP01.3 Add failing contract tests
- [x] ACP01.4 Add synthetic downstream consumer import coverage

## Phase 1

### End state

- Shared ACP interfaces and fake runtimes exist and fail in the expected places before implementation.

### Tests first

- Add failing tests for initialize, prompt streaming, permission correlation, filesystem callback shapes, terminal callback shapes, update event shapes, cancel, and load-session semantics.
- Add a downstream-consumer import test that is expected to pass once the contract modules exist, even before later runtime implementations are complete.

### Work

- Keep contracts explicit and narrow.
- Avoid implementing real runtime logic beyond what the fakes require.
- Document any intentionally reserved extension points for later tracks.

### Verify

- `uv run pytest tests/acp/test_contracts.py tests/acp/test_fake_agent_protocol.py`
- `uv run ruff check nanobot/acp tests/acp`

## Resume Instructions (Agent)

- Own the ACP interfaces. Other tracks should import from these files instead of creating local protocol abstractions.

## Decisions / Deviations Log

- 2026-03-09: This plan is the merge gate for Wave 1 because later tracks depend on shared ACP contracts.
- 2026-03-09: Shared contracts are published via `nanobot/acp/contracts.py` and `nanobot/acp/interfaces.py`; ad hoc prose notes are not the contract surface.
