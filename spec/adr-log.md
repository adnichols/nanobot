# Architectural Decision Log

This document records significant architectural decisions made in the nanobot project.

---

## ADR 0001: Telegram as ACP Control Surface
**Status:** Accepted (implemented and verified)
**Date:** 2026-03-12

### Context

nanobot already had most of the ACP backbone, but Telegram dropped most slash commands before they reached AgentLoop or ACPService. The user wanted Telegram to be the main control plane for OpenCode work, including slash-command-driven flows, without depending on a direct Telegram-to-OpenCode architecture.

Key constraints:
- ACP session reset, metadata preservation, and update visibility had integration gaps
- ACP permission and callback handling was not fully round-tripped back to the agent
- Some OpenCode actions would stall unless the runtime gap was closed
- Needed to support both trusted interactive sessions and future approval workflows

### Decision

We decided to:

1. **Keep Telegram Thin:** Telegram remains a thin pass-through surface for OpenCode slash commands rather than building a Telegram-specific command catalog. This avoids duplicating ACP-level command definitions.

2. **Trusted Session Detection:** Identify Telegram sessions by the `telegram:` session key prefix. This allows runtime discrimination between interactive Telegram sessions (trusted) and unattended cron sessions (policy-driven).

3. **Explicit Update Sink Lifecycle:** Clear stale ACP update subscriptions between prompts to prevent progress updates from leaking into the wrong callback context when ACP sessions are reused.

4. **Protocol Error Translation:** Translate terminal lifecycle errors to structured ACP protocol errors (`RequestError.invalid_params`) instead of letting internal SDK exceptions surface to users.

5. **Live Handler Registration:** Attach real filesystem and terminal handlers to the live ACP service path so Telegram-driven OpenCode sessions hit real handlers instead of adapter-only test doubles.

### Alternatives Considered

1. **Direct Telegram-to-OpenCode Architecture:** Rejected. The user explicitly wanted to avoid coupling Telegram directly to OpenCode. This architecture would have created a parallel path that bypassed nanobot's ACP infrastructure.

2. **Telegram-Specific Command Catalog:** Rejected. Building a Telegram-specific wrapper command catalog in nanobot would duplicate command definitions already present in the ACP agent. The thin pass-through approach is simpler and avoids this duplication.

3. **Adopting `opencode-telegram`:** Rejected. The `opencode-telegram` project was studied as a reference for `/command` support UX patterns, but it was not approved as a dependency, architecture template, or copied subsystem.

### Consequences

- **Positive:** Telegram users can now drive ACP agent workflows directly with slash commands
- **Positive:** Trusted single-user sessions default to approval-free execution
- **Positive:** Foundation exists for future approval workflows (`ask`/`deny` policies)
- **Positive:** Unattended cron behavior remains isolated from Telegram session policy
- **Negative:** Multi-user authorization is not yet supported (out of scope for this feature)

### Current State

- Implementation: `nanobot/channels/telegram.py`, `nanobot/agent/loop.py`, `nanobot/acp/service.py`
- Tests: `tests/test_telegram_channel.py`, `tests/acp/test_cli_routing.py`
- Architecture Doc: `spec/architecture/telegram-acp-routing.md`
- Plan: `thoughts/plans/2026-03-12-telegram-acp-slash-command-routing.md`

---

## Template for Future ADRs

## ADR NNNN: [Title]
**Status:** [Proposed | Accepted | Deprecated | Superseded]
**Date:** YYYY-MM-DD

### Context

[Describe the problem or situation that led to this decision. What forces are at play?]

### Decision

[What was decided? Be specific.]

### Alternatives Considered

[What other options were considered and why were they rejected?]

### Consequences

- **Positive:** [Benefits]
- **Negative:** [Trade-offs or risks]

### Current State

[Where is this decision reflected in the codebase?]
