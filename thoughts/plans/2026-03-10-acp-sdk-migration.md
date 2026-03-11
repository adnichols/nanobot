# ACP SDK Migration Plan

## Status

- ready

## Goal

Replace nanobot's custom "ACP" transport/runtime implementation with the official `agent-client-protocol` SDK, enabling proper communication with OpenCode and other ACP-compliant agents while preserving all nanobot-specific domain logic.

## Why this plan exists

The current nanobot implementation uses a custom stdio protocol incorrectly labeled as "ACP" that fails to communicate with OpenCode because it doesn't follow the actual ACP specification. Live testing confirmed the official ACP SDK works perfectly with OpenCode. This migration will:

1. Enable proper Telegram/WhatsApp → nanobot → OpenCode routing
2. Align nanobot transport with the ACP standard (like LSP for language servers)
3. Remove ~1,200 lines of custom transport code while keeping nanobot domain logic
4. Preserve all existing nanobot behaviors: permissions, sessions, cron, terminal, fs

## Authority and inputs

- **Repository guide:** `AGENTS.md`
- **Product intent:** `thoughts/specs/product_intent.md`
- **Live evidence:** SDK compatibility test passed (session/prompt works)
- **ACP specification:** https://agentclientprotocol.com/protocol/schema
- **SDK documentation:** https://agentclientprotocol.github.io/python-sdk/

## Dependencies

### External Dependencies (Already Present)
- `agent-client-protocol>=0.8.1` - Already in `pyproject.toml`, installed

### In-Repo Dependencies (This Plan Touches)
- `nanobot/acp/service.py` - Owns ACP service layer, consumes SDK adapter
- `nanobot/acp/store.py` - Owns session persistence
- `nanobot/acp/interfaces.py` - Protocol definitions for callbacks
- `nanobot/acp/types.py` - Domain types (NOT wire types), KEEP and adapt
- `nanobot/acp/permissions.py` - Permission broker, KEEP
- `nanobot/acp/updates.py` - Update rendering, KEEP
- `nanobot/acp/render.py` - Content rendering, KEEP
- `nanobot/acp/fs.py` - Filesystem adapter, KEEP
- `nanobot/acp/terminal.py` - Terminal adapter, KEEP
- `nanobot/acp/cron.py` - Cron integration, MUST update for unattended ACP
- `nanobot/agent/loop.py` - Routes to ACP service
- `nanobot/acp/__init__.py` - Public exports, MUST update

### Contract Track Interfaces (Consume, Don't Modify)
- `ACPCallbackRegistry` interface from `interfaces.py`
- `ACPSessionStore` interface from `interfaces.py`
- `ACPUpdateSink` interface from `interfaces.py`

## File Ownership

This plan owns:
- **NEW:** `nanobot/acp/sdk_client.py` - SDK transport adapter
- **NEW:** `nanobot/acp/sdk_types.py` - Type conversions
- **MODIFY:** `nanobot/acp/service.py` - Replace transport layer
- **MODIFY:** `nanobot/acp/__init__.py` - Update exports
- **MODIFY:** `nanobot/acp/cron.py` - Update for SDK-based ACP
- **DELETE:** `nanobot/acp/runtime.py` - Custom transport (after P3)
- **DELETE:** `nanobot/acp/client.py` - Custom client wrapper (after P3)
- **DELETE:** `nanobot/acp/opencode.py` - Custom OpenCode adapter (after P3)
- **DELETE:** Tests that only test custom runtime

This plan does NOT own:
- `nanobot/acp/types.py` - Keep, adapt imports
- `nanobot/acp/permissions.py` - Keep, ensure callbacks work
- `nanobot/acp/updates.py` - Keep, ensure notification routing works
- `nanobot/acp/render.py` - Keep, unchanged
- `nanobot/acp/fs.py` - Keep, unchanged
- `nanobot/acp/terminal.py` - Keep, unchanged
- `nanobot/acp/store.py` - Keep, unchanged
- `nanobot/acp/session.py` - Keep, unchanged
- `nanobot/acp/contracts.py` - Keep, unchanged
- `nanobot/agent/loop.py` - Verify compatibility only

## Progress

- [x] ACP01: Verify SDK API and lock version
- [x] ACP02: Create SDK transport adapter
- [x] ACP03: Update service layer to use SDK adapter
- [x] ACP04: Update cron integration for SDK-based ACP
- [x] ACP05: Verify agent loop compatibility
- [x] ACP06: Delete legacy transport code
- [x] ACP07: Adapt types.py imports and verify all tests

## Resume Instructions (Agent)

1. Read this plan fully
2. Identify first unchecked progress item (ACP01 → ACP07)
3. Read the corresponding phase section for implementation details
4. Execute phase step-by-step
5. Run `### Verify` commands after each phase
6. Ask user only for truly unresolvable decisions

## Product intent alignment

**Advances Outcome 1:** nanobot will route conversations through proper ACP-backed external agent sessions using standard transport.

**Advances Outcome 2:** Scheduled reminders and cron jobs continue to work with ACP backend (explicitly addressed in ACP04).

**Advances Outcome 3:** External agent support becomes truly configurable and provider-agnostic via the ACP standard.

**Experience Principle 3:** External agent delegation will finally feel "native, observable, and resumable" because the transport will actually work.

**Experience Principle 4:** Unattended automation (cron) remains safe by default with proper permission handling (explicitly addressed in ACP04).

**Quality Bar:** This directly addresses the "ACP routing hangs" issue that breaks session resume and restart recovery.

## Locked decisions

**Decision 1 (REUSE):** Use official `agent-client-protocol` SDK for transport layer.
- **Rationale:** SDK tested and proven compatible with OpenCode. Custom transport led to the current failure. SDK provides JSON-RPC transport we need.
- **External dependency:** Already approved and present in `pyproject.toml`.

**Decision 2 (ARCHITECTURE):** Transport swap only, keep nanobot domain layer.
- **Rationale:** The domain logic (permissions, sessions, rendering, fs, terminal) is correct and well-tested. Only the transport layer (runtime/client/opencode) is wrong.
- **Scope:** Replace how we talk to OpenCode, not what nanobot does with the responses.

**Decision 3 (KEEP types.py):** Adapt `nanobot/acp/types.py`, don't delete it.
- **Rationale:** `types.py` contains internal domain types (`ACPSessionRecord`, `ACPPermissionRequest`, `ACPUpdateEvent`) used across the ACP subsystem. It's not just wire types.
- **Action:** Keep file, update imports as needed after deleting custom runtime.

**Decision 4 (CRON):** Explicitly update `nanobot/acp/cron.py` for SDK-based ACP.
- **Rationale:** Scheduler/unattended automation is a product-intent outcome. Cron ACP sessions need explicit handling for session lifecycle and unattended permissions.

**Decision 5 (ADAPT tests):** Extend existing test suites, don't create parallel ones.
- **Rationale:** `tests/acp/test_contracts.py` and `tests/acp/test_acceptance_opencode.py` already cover the behaviors we need. Adapt them rather than creating redundant new suites.

**Decision 6 (VERSION):** Pin to `agent-client-protocol==0.8.1`.
- **Rationale:** Proven working version. Upgrade intentionally later after migration stabilizes.

## Acceptance criteria

### Must Have
- [ ] SDK transport connects to OpenCode via stdio
- [ ] `initialize` → `session/new` → `session/prompt` flow works end-to-end
- [ ] Telegram messages route through ACP (not fallback)
- [ ] Session persistence across restarts works
- [ ] Permission callbacks (fs, terminal) work with SDK
- [ ] Update rendering works with SDK notifications
- [ ] Cron jobs work with ACP backend (unattended automation)
- [ ] `load_session` handles agents without `loadSession` capability
- [ ] All existing tests pass (`uv run pytest`)
- [ ] Custom transport files deleted
- [ ] No broken imports remaining

### Should Have
- [ ] `pyproject.toml` pins exact SDK version
- [ ] Capability negotiation cached for session/load fallback
- [ ] Graceful degradation when ACP agent lacks features

## BDD Scenarios

### BDD1: Happy Path - SDK ACP Flow
```gherkin
Given nanobot gateway is running with OpenCode configured via SDK
When a Telegram user sends "hello"
Then nanobot creates ACP session via SDK's session/new
And nanobot sends prompt via SDK's session/prompt
And nanobot receives streaming session/update notifications
And nanobot renders updates to Telegram
And nanobot sends final response back to Telegram
And the response came from OpenCode (not local provider)
```

### BDD2: Session Persistence and Resume
```gherkin
Given nanobot was restarted
And a previous session binding exists in store
When nanobot checks agent capabilities from initialize response
And agent advertised loadSession capability
Then SDK adapter calls session/load to resume
And user continues conversation with context preserved
```

### BDD3: Session Resume Fallback (No loadSession)
```gherkin
Given nanobot was restarted
And a previous session binding exists in store
When nanobot checks agent capabilities from initialize response
And agent did NOT advertise loadSession capability
Then SDK adapter creates new session via session/new
And binds new ACP session to existing nanobot session
And user continues conversation (context may reset)
```

### BDD4: Permission Flow via SDK
```gherkin
Given ACP agent requests permission via session/update notification
When nanobot receives permission request notification
Then nanobot routes to permission broker
And user approves/denies via normal channel flow
And nanobot sends permission decision response to agent
And agent continues processing
```

### BDD5: ACP Hang - Fallback to Local Provider
```gherkin
Given OpenCode ACP process is not responding
When nanobot attempts ACP routing with 5s timeout
And ACP does not respond within timeout
Then nanobot logs "ACP routing timed out"
And nanobot cancels ACP session via session/cancel
And nanobot falls back to local provider
And user still receives a response
```

### BDD6: Cron ACP Integration (Unattended)
```gherkin
Given a cron job is configured to use ACP backend
When cron triggers unattended execution
Then nanobot creates ACP session for cron context
And nanobot uses unattended permission policy
And sends prompt via SDK
And routes response back to configured channel
And closes session after completion
```

### BDD7: Multi-Session Isolation
```gherkin
Given two different Telegram users (A and B)
When both send messages concurrently
Then SDK adapter creates separate ACP sessions
And User A's context does not leak to User B
And both users receive appropriate responses
```

## Phase-by-phase execution plan

### ACP01: Verify SDK API and Lock Version

#### End State
- SDK version pinned to `==0.8.1` in `pyproject.toml`
- Branch `feature/acp-sdk-migration` created
- Verify SDK API surface matches expectations

#### Tests First
```python
# tests/acp/test_sdk_verify.py
def test_sdk_version_pinned():
    """Verify exact SDK version is installed."""
    import acp
    assert acp.__version__ == "0.8.1"

def test_sdk_connection_importable():
    """Verify Connection class is importable."""
    from acp.connection import Connection
    assert Connection is not None

def test_sdk_schema_importable():
    """Verify schema types are importable."""
    from acp import schema
    assert schema.InitializeRequest is not None
    assert schema.NewSessionRequest is not None
    assert schema.PromptRequest is not None
```

#### Work
1. Update `pyproject.toml`: Change `agent-client-protocol>=0.8.1` to `agent-client-protocol==0.8.1`
2. Run `uv sync` to lock version
3. Create branch `feature/acp-sdk-migration`
4. Verify SDK imports match expected API

#### Expected files
- `pyproject.toml` (modified - pin version)
- `tests/acp/test_sdk_verify.py` (new)

#### Verify
```bash
uv sync
uv run python -c "import acp; print(acp.__version__)"  # Should print 0.8.1
uv run pytest tests/acp/test_sdk_verify.py -v
```

---

### ACP02: Create SDK Transport Adapter

#### End State
- `nanobot/acp/sdk_client.py` - Wraps SDK Connection
- `nanobot/acp/sdk_types.py` - Type conversions
- Adapter handles: connect, initialize, session/new, session/prompt, session/cancel
- Adapter routes notifications to nanobot callbacks

#### Tests First
```python
# tests/acp/test_sdk_adapter.py
@pytest.mark.asyncio
async def test_adapter_initializes_with_opencode():
    """SDK adapter can initialize with live OpenCode."""
    # Requires: opencode binary available
    # Create adapter, connect, verify initialize succeeds
    pass

@pytest.mark.asyncio
async def test_adapter_creates_session():
    """SDK adapter can create ACP session."""
    # Requires: opencode binary available
    # Create adapter, initialize, verify session/new returns valid ID
    pass

@pytest.mark.asyncio
async def test_adapter_receives_notifications():
    """SDK adapter routes notifications to callback."""
    # Mock handler, verify notifications are delivered
    pass
```

#### Work
1. Create `nanobot/acp/sdk_types.py`:
   - Type conversion: nanobot domain types ↔ SDK schema types
   - `to_sdk_initialize_params()`
   - `to_sdk_new_session_params()`
   - `to_sdk_prompt_params()`

2. Create `nanobot/acp/sdk_client.py`:
   - Class `SDKClient` wrapping `acp.Connection`
   - Methods: `initialize()`, `new_session()`, `prompt()`, `cancel()`, `close()`
   - Handler method for agent->client notifications (routes to callback registry)
   - Error mapping: SDK exceptions → nanobot exceptions

3. Notification routing:
   - When SDK receives `session/update`, route to `ACPUpdateSink`
   - When SDK receives `session/request_permission`, route to `ACPPermissionBroker`
   - When SDK receives `fs/read_text_file`, route to `FilesystemAdapter`
   - When SDK receives `terminal/create`, route to `TerminalAdapter`

#### Expected files
- `nanobot/acp/sdk_types.py` (new)
- `nanobot/acp/sdk_client.py` (new)
- `tests/acp/test_sdk_adapter.py` (new)

#### Verify
```bash
uv run pytest tests/acp/test_sdk_adapter.py -v
uv run ruff check nanobot/acp/sdk_types.py nanobot/acp/sdk_client.py
```

---

### ACP03: Update Service Layer

#### End State
- `nanobot/acp/service.py` uses `SDKClient` instead of `ACPClient`
- Service API unchanged (Agent Loop doesn't break)
- Session store integration preserved
- Callback registry integration preserved
- Capability negotiation for session/load

#### Tests First
```python
# Verify using adapted existing tests
# tests/acp/test_cli_routing.py should pass with SDK service
# tests/acp/test_session_store.py should pass
# tests/acp/test_recovery.py should pass
```

#### Work
1. Update `nanobot/acp/service.py`:
   - Replace `from nanobot.acp.client import ACPClient` with `from nanobot.acp.sdk_client import SDKClient`
   - Update `create_session()` to use SDK client
   - Cache capabilities from initialize response
   - Update `load_session()`:
     - Check if agent has `loadSession` capability (cached from initialize)
     - If yes: call `session/load`
     - If no: call `session/new` and rebind
   - Keep session store integration
   - Keep callback registry integration
   - Update error handling for SDK exceptions

2. Ensure public API unchanged:
   - `ACPService.create_session()`
   - `ACPService.load_session()`
   - `ACPService.prompt()`
   - `ACPService.cancel_operation()`

#### Expected files
- `nanobot/acp/service.py` (modified)

#### Verify
```bash
uv run pytest tests/acp/test_cli_routing.py -v
uv run pytest tests/acp/test_session_store.py -v
uv run pytest tests/acp/test_recovery.py -v
```

---

### ACP04: Update Cron Integration

#### End State
- `nanobot/acp/cron.py` uses SDK-based service
- Cron ACP sessions work with unattended permission policy
- Cron properly creates, uses, and closes ACP sessions

#### Tests First
```python
# Update tests/acp/test_cron_acp.py
# Verify cron can create ACP session via SDK
# Verify unattended permission policy works
# Verify session cleanup after cron completion
```

#### Work
1. Update `nanobot/acp/cron.py`:
   - Verify imports from service module work
   - Update cron session creation to use SDK-based service
   - Ensure unattended permission policy still applies
   - Ensure proper session cleanup after execution

2. No API changes expected - service layer stays compatible

#### Expected files
- `nanobot/acp/cron.py` (minimal updates if any)

#### Verify
```bash
uv run pytest tests/acp/test_cron_acp.py -v
```

---

### ACP05: Verify Agent Loop Compatibility

#### End State
- `nanobot/agent/loop.py` works with SDK-based service
- ACP routing works end-to-end
- Timeout/cancel behavior preserved
- Fallback to local provider works

#### Tests First
```python
# Verify using existing tests
# tests/acp/test_cli_routing.py
# tests/test_task_cancel.py
```

#### Work
1. Verify `nanobot/agent/loop.py`:
   - Service imports work
   - `_route_to_acp()` uses new service correctly
   - Timeout handling works
   - Fallback works when ACP unavailable

2. Minimal changes expected - service API is compatible

#### Expected files
- No changes expected, or minimal import updates

#### Verify
```bash
uv run pytest tests/acp/test_cli_routing.py -v
uv run pytest tests/test_task_cancel.py -v
```

---

### ACP06: Delete Legacy Transport Code

#### End State
- `nanobot/acp/runtime.py` deleted
- `nanobot/acp/client.py` deleted
- `nanobot/acp/opencode.py` deleted
- `nanobot/acp/__init__.py` exports updated
- No broken imports remaining

#### Tests First
```bash
# Verify no import errors
uv run python -c "from nanobot.acp import ACPService; print('Imports OK')"
```

#### Work
1. Delete files:
   - `nanobot/acp/runtime.py`
   - `nanobot/acp/client.py`
   - `nanobot/acp/opencode.py`

2. Update `nanobot/acp/__init__.py`:
   - Remove exports for deleted modules
   - Keep exports for modules we kept
   - Add export for new `SDKClient` if needed

3. Update `nanobot/acp/types.py`:
   - Remove imports from deleted modules
   - Keep internal domain types

4. Verify no broken imports:
   - Check all files that imported deleted modules
   - Update or remove stale imports

5. Delete tests that only test deleted code:
   - `tests/acp/test_runtime_core.py`
   - `tests/acp/test_opencode_integration.py`
   - `tests/acp/test_fake_agent_protocol.py`

#### Expected files
- `nanobot/acp/runtime.py` (deleted)
- `nanobot/acp/client.py` (deleted)
- `nanobot/acp/opencode.py` (deleted)
- `nanobot/acp/__init__.py` (modified)
- `nanobot/acp/types.py` (modified - remove stale imports)

#### Verify
```bash
uv run ruff check nanobot/acp/
uv run python -c "from nanobot.acp import ACPService; print('Imports OK')"
# Fix any broken imports before proceeding
```

---

### ACP07: Final Verification and Test Suite

#### End State
- All tests pass
- SDK integration verified
- ACP compliance verified
- No regressions

#### Tests First
```bash
# Run full test suite
uv run pytest tests/acp/ -v
```

#### Work
1. Adapt existing test suites:
   - Update `tests/acp/test_acceptance_opencode.py` for SDK
   - Update `tests/acp/test_contracts.py` for SDK
   - Verify `tests/acp/test_permission_broker.py` still works
   - Verify `tests/acp/test_update_rendering.py` still works
   - Verify `tests/acp/test_terminal_manager.py` still works
   - Verify `tests/acp/test_fs_adapter.py` still works

2. Create minimal SDK-specific tests only if gaps exist:
   - Only add new test files if existing suites don't cover SDK behaviors

3. Manual verification (opt-in):
   ```bash
   # If OpenCode available:
   NANOBOT_TEST_OPENCODE=1 uv run pytest tests/acp/test_acceptance_opencode.py -v -m opencode_real
   ```

#### Expected files
- Updated existing test files (not new parallel suites)

#### Verify
```bash
# Full verification
uv run ruff check .
uv run pytest tests/acp/ -v
uv run pytest  # Full suite

# Check no old protocol references remain
grep -r "ACPAgentRuntime" nanobot/ || echo "No old runtime references"
grep -r "from nanobot.acp import.*runtime" nanobot/ || echo "No runtime imports"
grep -r "from nanobot.acp import.*client" nanobot/ || echo "No client imports"
grep -r "from nanobot.acp import.*opencode" nanobot/ || echo "No opencode imports"
```

---

## Verify

### Phase verification commands

ACP01: `uv run pytest tests/acp/test_sdk_verify.py -v`
ACP02: `uv run pytest tests/acp/test_sdk_adapter.py -v`
ACP03: `uv run pytest tests/acp/test_cli_routing.py tests/acp/test_session_store.py tests/acp/test_recovery.py -v`
ACP04: `uv run pytest tests/acp/test_cron_acp.py -v`
ACP05: `uv run pytest tests/acp/test_cli_routing.py tests/test_task_cancel.py -v`
ACP06: `uv run ruff check nanobot/acp/ && uv run python -c "from nanobot.acp import ACPService"`
ACP07: `uv run ruff check . && uv run pytest`

### Final acceptance verification

```bash
# 1. Lint passes
uv run ruff check .

# 2. Tests pass
uv run pytest

# 3. SDK version pinned
uv run python -c "import acp; assert acp.__version__ == '0.8.1', f'Wrong version: {acp.__version__}'"

# 4. No old transport references
grep -r "ACPAgentRuntime" nanobot/ || echo "✓ No old runtime references"
grep -r "from nanobot.acp import.*runtime" nanobot/ || echo "✓ No runtime imports"
grep -r "from nanobot.acp import.*client" nanobot/ || echo "✓ No client imports"
grep -r "from nanobot.acp import.*opencode" nanobot/ || echo "✓ No opencode imports"

# 5. Manual test (if environment allows)
# Start gateway, verify Telegram → OpenCode works via ACP (not fallback)
```

---

## Delivery order

1. **ACP01 → ACP02 → ACP03 → ACP04 → ACP05 → ACP06 → ACP07** (sequential)
2. Each phase must pass `### Verify` before proceeding
3. If a phase fails, iterate until it passes, then continue

---

## Non-goals

- **Not adding HTTP transport** - SDK supports it, but stdio is default and proven working
- **Not implementing all ACP features** - Focus on core: initialize, session/new|load, session/prompt, session/cancel
- **Not supporting multiple ACP agents simultaneously** - One ACP backend per deployment
- **Not backward compatibility** - Delete old transport entirely
- **Not ACP agent mode** - nanobot remains a client
- **Not extending ACP spec** - Use standard methods only
- **Not changing nanobot domain logic** - Keep permissions, sessions, rendering, fs, terminal as-is

---

## Decisions / Deviations Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-10 | Use SDK v0.8.1 | Proven compatible with OpenCode in live test |
| 2026-03-10 | Transport swap only, keep domain layer | Domain logic (permissions, sessions) is correct; only transport is wrong |
| 2026-03-10 | Keep types.py, don't delete | Contains internal domain types used across ACP subsystem |
| 2026-03-10 | Update cron.py explicitly | Unattended automation is product-intent requirement |
| 2026-03-10 | Adapt existing tests, don't create parallel suites | Reuse doctrine: extend `test_contracts.py` and `test_acceptance_opencode.py` |
| 2026-03-10 | Add capability negotiation for session/load | ACP spec: session/load is optional, need fallback when agent lacks it |
| 2026-03-10 | Pin exact SDK version | Stability: upgrade intentionally after migration completes |

---

*Document Version: 3.0*  
*Last Updated: 2026-03-10*  
*Incorporates: GPT5.4 review feedback*  
*Format: Canonical execution-ready plan*
