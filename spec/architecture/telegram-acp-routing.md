# Telegram ACP Slash Command Routing

**Last Updated:** 2026-03-13
**Status:** ✅ Implemented
**Plan:** thoughts/plans/2026-03-12-telegram-acp-slash-command-routing.md

## Overview

This feature makes Telegram a first-class control surface for ACP (Agent Communication Protocol) agents, particularly OpenCode. It enables users to drive ACP agent workflows directly from Telegram using slash commands, with trusted single-user sessions defaulting to approval-free execution while preserving resumable sessions, channel-native progress visibility, and a foundation for future approval workflows.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        Telegram Channel                          │
│                    (nanobot/channels/telegram.py)               │
├─────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│ │   Handler    │  │ Normalization│  │ Command Menu         │  │
│ │   Registry   │  │  (/cmd@bot)  │  │ Registration + Retry │  │
│ └──────────────┘  └──────────────┘  └──────────────────────┘  │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Agent Loop                             │
│                      (nanobot/agent/loop.py)                   │
├─────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│ │  Command     │  │  ACP Route   │  │  Update Sink       │  │
│ │  Routing     │  │  to ACP      │  │  Management        │  │
│ │  (/new etc.) │  │  Service     │  │  (clear/rebind)    │  │
│ └──────────────┘  └──────────────┘  └──────────────────────┘  │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                        ACP Service                             │
│                     (nanobot/acp/service.py)                   │
├─────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│ │   Session    │  │ Permission   │  │ Live Handler       │  │
│ │   Mgmt       │  │   Broker     │  │ Registration       │  │
│ │ (reset etc.) │  │  (auto/ask)  │  │ (fs/terminal)      │  │
│ └──────────────┘  └──────────────┘  └──────────────────────┘  │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                       SDK Client                               │
│                    (nanobot/acp/sdk_client.py)                 │
├─────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│ │ Callback     │  │ Permission   │  │ Terminal Lifecycle   │  │
│ │ Decisions    │  │   Handling   │  │ Error Translation    │  │
│ │ (notification)│  │              │  │                      │  │
│ └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Behaviors

### 1. Telegram Slash Command Forwarding
- **Behavior:** Telegram forwards arbitrary OpenCode slash commands (`/model`, `/init`, etc.) into the nanobot bus and ACP path
- **Implementation:** `TelegramChannel._forward_command()` at `nanobot/channels/telegram.py:478-504`
- **Tests:** `tests/test_telegram_channel.py::test_unknown_slash_command_forwards_to_bus`

### 2. Bot Mention Normalization
- **Behavior:** Group chat commands with bot mentions (`/command@nanobot args`) are normalized to `/command args` before routing
- **Implementation:** `TelegramChannel._normalize_command_text()` at `nanobot/channels/telegram.py:456-476`
- **Tests:** `tests/test_telegram_channel.py::test_group_command_bot_mention_is_normalized`

### 3. Other Bot Filtering
- **Behavior:** Commands addressed to other bots (`/command@otherbot`) are ignored
- **Implementation:** Same normalization function checks bot username match
- **Tests:** `tests/test_telegram_channel.py::test_group_command_for_other_bot_is_ignored`

### 4. Local Command Handling
- **Behavior:** `/start` and `/help` remain Telegram-local; `/new` and `/stop` are forwarded to the bus for local handling
- **Implementation:** Handler registration order in `nanobot/channels/telegram.py:253-256`
- **Tests:** `tests/test_telegram_channel.py::test_new_command_forwards_to_bus`, `test_stop_command_forwards_to_bus`

### 5. ACP Session Reset
- **Behavior:** `/new` in ACP mode clears both the live client and the persisted ACP binding, ensuring a fresh OpenCode session
- **Implementation:** `ACPService.reset_session()` at `nanobot/acp/service.py:390-402`
- **Tests:** `tests/acp/test_cli_routing.py::test_acp_new_clears_persisted_binding_before_next_session_load`

### 6. Trusted Interactive Sessions
- **Behavior:** Telegram sessions use `policy="auto"` which resolves to approval-free execution for trusted interactive sessions
- **Implementation:** `PermissionBrokerFactory` at `nanobot/acp/permissions.py:391-541`
- **Tests:** `tests/acp/test_cli_routing.py::test_trusted_telegram_auto_policy_resolves_without_prompting`

### 7. Update Sink Management
- **Behavior:** Stale ACP update sinks are cleared between prompts to prevent progress leaking into wrong callbacks
- **Implementation:** `ACPService.clear_update_subscription()` at `nanobot/acp/service.py:333-336`
- **Tests:** `tests/acp/test_cli_routing.py::test_acp_routing_clears_stale_update_subscription_when_progress_hidden`

### 8. Command Menu Registration
- **Behavior:** Telegram's native command menu includes both local commands and ACP-advertised commands; startup retry handles delayed ACP discovery
- **Implementation:** `TelegramChannel._refresh_bot_commands_until_acp_ready()` at `nanobot/channels/telegram.py:201-229`
- **Tests:** `tests/test_telegram_channel.py::test_refresh_bot_commands_retries_until_acp_commands_appear`

### 9. Metadata Preservation
- **Behavior:** Inbound Telegram metadata (message_id, user info) is preserved on ACP responses for reply quoting
- **Implementation:** `AgentLoop._process_message()` at `nanobot/agent/loop.py:868-881`
- **Tests:** `tests/acp/test_cli_routing.py::test_acp_routing_preserves_inbound_metadata_on_final_response`

### 10. Progress Visibility
- **Behavior:** ACP updates (tool calls, thinking, results) can be surfaced even when live content streaming is disabled
- **Implementation:** `AgentLoop._route_to_acp()` visibility checks at `nanobot/agent/loop.py:252-289`
- **Tests:** `tests/acp/test_cli_routing.py::test_acp_routing_subscribes_to_visible_updates_without_live_content`

### 11. Callback Round-Trips
- **Behavior:** Permission, filesystem, and terminal callback decisions are sent back to the ACP agent
- **Implementation:** `SDKNotificationHandler._handle_permission_request()` at `nanobot/acp/sdk_client.py:688-769`
- **Tests:** `tests/acp/test_sdk_adapter.py::test_permission_decision_is_sent_back_over_sdk_connection`

### 12. Live Handler Registration
- **Behavior:** Real filesystem and terminal handlers are registered on the live ACP path
- **Implementation:** `commands.py:76-82` creates handlers; `ACPService.register_*_callback()` methods wire them
- **Tests:** `tests/acp/test_cli_routing.py::test_live_acp_service_registers_real_filesystem_and_terminal_handlers_before_prompting`

### 13. Terminal Error Translation
- **Behavior:** Terminal lifecycle errors (invalid terminal ID, etc.) are translated to structured protocol errors instead of internal exceptions
- **Implementation:** `SDKNotificationHandler` terminal methods at `nanobot/acp/sdk_client.py:1408-1500`
- **Tests:** `tests/acp/test_sdk_adapter.py::test_invalid_terminal_lifecycle_requests_raise_protocol_errors`

## API Contracts

### ACP Service Interface

```python
class ACPService:
    def reset_session(self, nanobot_session_key: str) -> None:
        """Clear live client and persisted binding for fresh session."""
        
    def clear_update_subscription(self, nanobot_session_key: str) -> None:
        """Clear the active update sink for a session."""
        
    def register_filesystem_callback(self, handler) -> None:
        """Register filesystem handler for live ACP callbacks."""
        
    def register_terminal_callback(self, handler) -> None:
        """Register terminal handler for live ACP callbacks."""
```

### Permission Broker Factory

```python
class PermissionBrokerFactory:
    @staticmethod
    def create_for_session(
        session_key: str,
        agent_policy: str,
        permission_policies: dict,
        callback_registry,
    ) -> ACPPermissionBroker:
        """Create appropriate broker for session type.
        
        Telegram sessions (telegram: prefix) get trusted interactive defaults.
        Cron/unattended sessions get UnattendedPermissionPolicy.
        """
```

## Configuration

### Relevant Config Options

```python
# config.channels.telegram
reply_to_message: bool = True  # Preserve message_id for quoting

# config.channels.acp_stream_content
acp_stream_content: bool = False  # Enable live content streaming
acp_show_tool_calls: bool = True   # Show tool call progress
acp_show_tool_results: bool = True # Show tool results
acp_show_thinking: bool = True    # Show thinking updates
acp_show_system: bool = True     # Show system notices

# config.acp.agents[agent_id].policy
policy: str = "auto"  # auto (trusted allow), ask (prompt), deny (block)
```

## Constraints

1. **Single-User Trusted Sessions:** Current implementation assumes trusted single-user Telegram sessions. Multi-user authorization is out of scope.

2. **No Inline Keyboards:** Feature does not add Telegram inline keyboards or complex UI elements. It remains text/command-based.

3. **Policy Boundaries:** Unattended cron sessions maintain their own permission policies and do not inherit Telegram's trusted defaults.

4. **External Dependency:** No new external dependencies were added. The `opencode-telegram` wrapper was studied for UX patterns but not adopted as a dependency.

## Integration Points

### Telegram Integration
- Uses `python-telegram-bot` library
- Leverages existing `TelegramChannel` message handling
- Maintains existing ACL, typing indicators, and media behavior

### ACP Integration
- Integrates with `ACPService` for session management
- Uses `SDKClient` for ACP protocol communication
- Leverages `ACPSessionBindingStore` for persistence

### Bus Integration
- Commands flow through nanobot's message bus
- Metadata preserved from channel through to ACP and back

## Testing

### Test Coverage

| Test File | Coverage | Count |
|-----------|----------|-------|
| `tests/test_telegram_channel.py` | Telegram channel behaviors | 15 passed |
| `tests/acp/test_cli_routing.py` | ACP routing integration | 48 passed |
| `tests/acp/test_sdk_adapter.py` | SDK client callbacks | 40 passed |
| `tests/acp/test_cron_acp.py` | Cron/unattended isolation | 20 passed |

### Running Tests

```bash
# Telegram channel tests
uv run pytest tests/test_telegram_channel.py -v

# ACP routing tests
uv run pytest tests/acp/test_cli_routing.py -v

# All ACP tests
uv run pytest tests/acp/ -v

# Full suite with linting
uv run ruff check . && uv run pytest
```

## Implementation Notes

### Key Design Decisions

1. **Thin Telegram Layer:** Telegram remains a thin pass-through rather than building a Telegram-specific command catalog. This keeps the architecture simple and avoids duplicating ACP-level command definitions.

2. **Trusted Session Detection:** Telegram sessions are identified by the `telegram:` session key prefix. This allows runtime discrimination between interactive Telegram sessions and unattended cron sessions.

3. **Update Sink Lifecycle:** Explicit clearing of update subscriptions between prompts prevents progress updates from leaking into the wrong callback context when ACP sessions are reused.

4. **Protocol Error Translation:** Terminal lifecycle errors that would surface as internal SDK exceptions are now caught and translated to structured ACP protocol errors (`RequestError.invalid_params`).

### Divergences from Original Plan

**None.** All features claimed in the plan are fully implemented. Two features were added beyond the original plan during review hardening:

1. **Terminal Error Translation:** Added to prevent internal exceptions from surfacing to users
2. **Available Commands Caching:** Added to support command menu registration from ACP-advertised commands

## References

- **Plan:** `thoughts/plans/2026-03-12-telegram-acp-slash-command-routing.md`
- **Verification:** `thoughts/validation/2026-03-12-telegram-acp-routing-verification.md`
- **ADR:** See `spec/adr-log.md` for architectural decisions
- **Product Intent:** `thoughts/specs/product_intent.md`
