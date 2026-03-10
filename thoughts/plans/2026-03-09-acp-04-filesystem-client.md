# ACP-04 Filesystem Client

## Status

- ready

## Goal

- Implement ACP filesystem client methods with nanobot safety policy.

## Product intent alignment

- Advances Outcome 1 by enabling full ACP client capability for file access.
- Supports Principles 3 and 4.

## Dependencies

- `ACP-00`
- `ACP-01`
- integrates with callback registration from `ACP-03`

## File ownership

- `nanobot/acp/fs.py`
- `tests/acp/test_fs_adapter.py`

## ACP interfaces consumed

- `ACPFilesystemHandler` and registration hooks from `ACP-01` and `ACP-03`
- shared session and request types from `ACP-01`

## Acceptance criteria

- ACP `fs/read_text_file` and `fs/write_text_file` are implemented.
- Workspace restrictions and path safety rules are enforced consistently.
- Errors are mapped into clear ACP-appropriate failures and are covered by tests.

## BDD scenarios

- Given a file inside the workspace, when OpenCode requests `read_text_file`, then nanobot returns the expected content slice.
- Given a path outside the allowed workspace, when a read or write is requested, then nanobot denies it safely.
- Given a permitted write request, when the adapter persists text, then the resulting file content matches exactly.

## Progress

- [x] ACP04.1 Add failing filesystem tests
- [x] ACP04.2 Implement read adapter (fs/read_text_file)
- [x] ACP04.3 Implement write adapter (fs/write_text_file)
- [x] ACP04.4 Validate path policy and error mapping (11 tests passing)

## Phase 1

### End state

- ACP filesystem callbacks are production-usable and policy-safe.

### Tests first

- Add failing tests for allowed read, denied read, allowed write, denied write, and line/limit behavior.

### Work

- Reuse repo safety constraints where practical.
- Do not implement terminal behavior or CLI wiring here.

### Verify

- `uv run pytest tests/acp/test_fs_adapter.py`
- `uv run ruff check nanobot/acp tests/acp`

## Resume Instructions (Agent)

- Integrate only through the callback interfaces published by `ACP-03`. Do not edit shared config or CLI files.

## Decisions / Deviations Log

- 2026-03-09: Filesystem support is part of full ACP functionality and is not deferred behind a reduced-capability mode.
