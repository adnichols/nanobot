# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Telegram ACP Slash Command Routing] - 2026-03-13

### Added

- **Telegram slash command forwarding** - Telegram now forwards arbitrary OpenCode slash commands (`/model`, `/init`, etc.) into the nanobot bus and ACP path
- **Bot mention normalization** - Group chat commands with bot mentions (`/command@nanobot args`) are normalized to `/command args` before routing
- **Other bot filtering** - Commands addressed to other bots (`/command@otherbot`) are ignored to prevent command hijacking
- **ACP session reset** - `/new` in ACP mode clears both live client and persisted binding for truly fresh OpenCode sessions
- **Trusted interactive sessions** - Telegram sessions use `policy="auto"` which defaults to approval-free execution for single-user trusted sessions
- **Update sink management** - Stale ACP update sinks are cleared between prompts to prevent progress update leaks
- **Command menu registration with retry** - Telegram's native command menu includes ACP-advertised commands; startup retry handles delayed ACP discovery
- **Metadata preservation** - Inbound Telegram metadata (message_id, user info) preserved on ACP responses for reply quoting
- **Progress visibility** - ACP updates (tool calls, thinking, results) can surface even when live content streaming is disabled
- **Callback round-trips** - Permission, filesystem, and terminal callback decisions are sent back to the ACP agent over the SDK connection
- **Live handler registration** - Real filesystem and terminal handlers registered on live ACP path (not just test doubles)
- **Terminal error translation** - Terminal lifecycle errors translated to structured ACP protocol errors instead of internal exceptions

### Changed

- `AgentLoop` now subscribes to ACP updates based on visibility flags independent of `acp_stream_content` flag
- `TelegramChannel` handler registration reordered so explicit local commands run first, then generic command forwarding
- `ACPService` now includes `reset_session()` method for fresh session semantics beyond `shutdown_session()`
- Permission broker factory now discriminates by session key prefix (`telegram:` vs cron keys)

### Technical Details

- **Implementation files:**
  - `nanobot/channels/telegram.py` - Command forwarding, normalization, menu registration
  - `nanobot/agent/loop.py` - ACP routing, update sink management
  - `nanobot/acp/service.py` - Session reset, handler registration
  - `nanobot/acp/permissions.py` - Trusted session detection, broker factory
  - `nanobot/acp/sdk_client.py` - Callback decisions, error translation

- **Test coverage:**
  - `tests/test_telegram_channel.py` - 15 tests covering command routing
  - `tests/acp/test_cli_routing.py` - 48 tests covering ACP integration
  - `tests/acp/test_sdk_adapter.py` - 40 tests covering SDK client
  - All tests passing with zero linting violations

- **Verified against plan:**
  - 13/13 behaviors verified as implemented
  - 0 divergences from specification
  - 2 features added beyond plan (terminal error translation, command caching)

- **Architecture decisions:**
  - Telegram remains thin pass-through (no Telegram-specific command catalog)
  - Trusted sessions identified by `telegram:` session key prefix
  - Explicit update sink lifecycle prevents callback context leaks
  - See `spec/adr-log.md` for full ADR

### Documentation

- Architecture: `spec/architecture/telegram-acp-routing.md`
- ADR: `spec/adr-log.md` (ADR 0001)
- Plan: `thoughts/plans/2026-03-12-telegram-acp-slash-command-routing.md`
- Verification: `thoughts/validation/2026-03-12-telegram-acp-routing-verification.md`
