# ACP (Agent Client Protocol) Implementation Plan

**Status:** Draft  
**Created:** 2026-03-10  
**Owner:** nanobot ACP Track  
**Goal:** Implement proper ACP specification compliance to replace the current custom protocol

---

## 1. Background & Problem Statement

### What Went Wrong

The current nanobot "ACP" implementation is **not** the Agent Client Protocol. It is a custom internal protocol that was built without reference to the actual ACP specification:

| Aspect | Current (Wrong) | Real ACP Spec |
|--------|----------------|---------------|
| **Transport** | Custom JSON lines over stdio | JSON-RPC 2.0 over stdio or HTTP |
| **Message Format** | `{"type": "prompt", "session_id": "..."}` | `{"jsonrpc": "2.0", "method": "session/prompt", "id": 1}` |
| **Initialization** | Simple dict with session_id | Full capability negotiation via `initialize` |
| **Methods** | Ad-hoc `type` field | Standard methods: `initialize`, `session/new`, `session/prompt` |
| **Tool System** | Custom `tool_call` type | MCP-compliant tools via `tools/list`, `tools/call` |
| **Cancellation** | Custom cancel message | JSON-RPC `$/cancel` notification |

### Why This Matters

1. **OpenCode Compatibility**: OpenCode advertises ACP support but expects the real ACP protocol
2. **Ecosystem Compatibility**: Other ACP-compliant agents (Claude Code, Gemini CLI, Codex CLI) won't work with nanobot
3. **Future-Proofing**: ACP is becoming the standard for agent communication (like LSP for language servers)
4. **Correctness**: The current implementation hangs because OpenCode doesn't understand nanobot's custom protocol

---

## 2. ACP Specification Reference

### What is ACP?

The **Agent Client Protocol (ACP)** is an open standard for communication between AI coding agents and their clients (IDEs, editors, orchestrators). It is maintained at [agentclientprotocol.com](https://agentclientprotocol.com).

**Key Documents:**
- Overview: https://agentclientprotocol.com/protocol/overview
- Schema: https://agentclientprotocol.com/protocol/schema
- Initialization: https://agentclientprotocol.com/protocol/initialization
- Prompt Turn: https://agentclientprotocol.com/protocol/prompt-turn

### Core Concepts

#### Communication Model
- **JSON-RPC 2.0** over stdio (primary) or HTTP/SSE (optional)
- **Methods**: Request-response pairs with `id`, `method`, `params`, `result`/`error`
- **Notifications**: One-way messages without response (e.g., `session/cancel`)

#### Message Flow

```
1. Initialization Phase
   Client → Agent: initialize (capability negotiation)
   Client → Agent: authenticate (if required)

2. Session Setup
   Client → Agent: session/new (create new session)
   OR
   Client → Agent: session/load (resume existing)

3. Prompt Turn
   Client → Agent: session/prompt (send user message)
   Agent → Client: session/update (streaming progress)
   Agent → Client: fs/read_text_file (file operations)
   Agent → Client: session/request_permission (tool permissions)
   Client → Agent: session/cancel (interrupt)
   Agent → Client: session/prompt response (complete)
```

### Standard Methods

#### Agent Methods (Called by Client)

| Method | Description | Required |
|--------|-------------|----------|
| `initialize` | Negotiate protocol version & capabilities | Yes |
| `authenticate` | Authenticate client if required | Conditional |
| `session/new` | Create new conversation session | Yes |
| `session/load` | Resume existing session | Optional |
| `session/prompt` | Send user message to agent | Yes |
| `session/cancel` | Cancel ongoing operations (notification) | Yes |
| `session/set_mode` | Switch agent operating mode | Optional |
| `session/list` | List existing sessions | Optional |

#### Client Methods (Called by Agent)

| Method | Description | Required |
|--------|-------------|----------|
| `session/update` | Stream session updates (notification) | Yes |
| `session/request_permission` | Request user authorization | Yes |
| `fs/read_text_file` | Read file contents | Optional |
| `fs/write_text_file` | Write file contents | Optional |
| `terminal/create` | Execute command in terminal | Optional |
| `terminal/output` | Get terminal output | Optional |

### Key Types

#### Initialize Request/Response

```json
// Request
{
  "jsonrpc": "2.0",
  "method": "initialize",
  "params": {
    "protocolVersion": 1,
    "clientCapabilities": {
      "fs": {"readTextFile": true, "writeTextFile": false},
      "terminal": false
    },
    "clientInfo": {"name": "nanobot", "version": "0.1.0"}
  },
  "id": 1
}

// Response
{
  "jsonrpc": "2.0",
  "result": {
    "protocolVersion": 1,
    "agentCapabilities": {
      "loadSession": true,
      "mcpCapabilities": {"http": false, "sse": false},
      "promptCapabilities": {"audio": false, "embeddedContext": true, "image": false},
      "sessionCapabilities": {"list": {}, "resume": {}, "fork": {}}
    },
    "agentInfo": {"name": "OpenCode", "version": "1.2.24"},
    "authMethods": []
  },
  "id": 1
}
```

#### Session/New Request/Response

```json
// Request
{
  "jsonrpc": "2.0",
  "method": "session/new",
  "params": {
    "cwd": "/home/anichols/code/3p/nanobot",
    "mcpServers": []
  },
  "id": 2
}

// Response
{
  "jsonrpc": "2.0",
  "result": {
    "sessionId": "ses_abc123...",
    "modes": {...},
    "configOptions": [...]
  },
  "id": 2
}
```

---

## 3. Implementation Plan

### Phase 1: Foundation (Week 1)

**Goal:** Create proper ACP types and transport layer

**Tasks:**
1. Create ACP specification types (`nanobot/acp/spec_types.py`)
2. Implement JSON-RPC transport (`nanobot/acp/jsonrpc.py`)
3. Update type definitions for ACP compliance

### Phase 2: Client Implementation (Week 2)

**Goal:** Implement ACP client that can communicate with real ACP agents

**Tasks:**
1. Create ACP spec client (`nanobot/acp/spec_client.py`)
2. Implement client-side handlers (`nanobot/acp/client_handlers.py`)
3. Update service layer to use new client

### Phase 3: Integration (Week 3)

**Goal:** Wire ACP implementation into nanobot agent loop

**Tasks:**
1. Update Agent Loop to use ACP client
2. Update configuration for ACP
3. Add feature flags for gradual migration

### Phase 4: Testing & Validation (Week 4)

**Goal:** Comprehensive testing against real ACP agents

**Tasks:**
1. Create ACP-specific test suite
2. Compliance testing
3. Integration testing

### Phase 5: Documentation & Migration (Week 5)

**Goal:** Document the spec and migrate from legacy

**Tasks:**
1. Create ACP specification document
2. Update developer documentation
3. Deprecate legacy protocol

---

## 4. Architecture

### Proposed Structure

```
nanobot/acp/
├── __init__.py              # Public API
├── spec_types.py            # ACP specification types (NEW)
├── jsonrpc.py               # JSON-RPC transport (NEW)
├── spec_client.py           # ACP spec client (NEW)
├── client_handlers.py       # Client-side method handlers (NEW)
├── service.py               # Updated to use spec client
└── ... (existing files)
```

---

## 5. Acceptance Criteria

- [ ] ACP spec types implemented
- [ ] JSON-RPC transport working
- [ ] ACP client can initialize with OpenCode
- [ ] ACP client can create sessions
- [ ] ACP client can send prompts and receive responses
- [ ] Telegram/WhatsApp messages route through ACP successfully
- [ ] Fallback to local provider still works
- [ ] All existing tests pass
- [ ] Documentation updated

---

## 6. Preventing Future Mistakes

### Lessons Learned

1. **Always check for standards first** - ACP is a published spec
2. **Read the documentation** - OpenCode's docs clearly state it uses ACP
3. **Verify protocol compliance** - Test against the actual spec
4. **Name things correctly** - Don't call something "ACP" if it's not the ACP spec

### Process Improvements

1. **Specification-first development** - Document the spec first
2. **Reference documentation in repo** - Keep relevant spec sections
3. **Compliance tests** - Write tests that verify spec compliance
4. **Regular spec reviews** - Check for spec updates quarterly

---

## 7. Resources

### Official ACP Documentation
- Main site: https://agentclientprotocol.com
- Overview: https://agentclientprotocol.com/protocol/overview
- Schema: https://agentclientprotocol.com/protocol/schema

### OpenCode Documentation
- ACP Support: https://open-code.ai/en/docs/acp

---

## 8. Next Steps

1. **Review this plan** - Get feedback from stakeholders
2. **Clarify OpenCode behavior** - Investigate why `session/prompt` doesn't work
3. **Create detailed Phase 1 tickets** - Break down into actionable tasks
4. **Begin implementation** - Start with types and transport layer

---

*Document Version: 1.0*  
*Last Updated: 2026-03-10*
