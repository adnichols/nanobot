================================================================================
VERIFICATION REPORT: Telegram ACP Slash Command Routing
================================================================================

VERIFIED MATCHES (Plan = Code)
------------------------------
[x] Telegram slash command forwarding to ACP
    Location: nanobot/channels/telegram.py:478-504
    Tests: tests/test_telegram_channel.py::test_unknown_slash_command_forwards_to_bus

[x] Bot mention normalization (/command@botname → /command)
    Location: nanobot/channels/telegram.py:456-476
    Tests: tests/test_telegram_channel.py::test_group_command_bot_mention_is_normalized

[x] Other bot command filtering (@otherbot commands ignored)
    Location: nanobot/channels/telegram.py:456-476
    Tests: tests/test_telegram_channel.py::test_group_command_for_other_bot_is_ignored

[x] ACP session reset (/new clears binding and live client)
    Location: nanobot/acp/service.py:390-402
    Tests: tests/acp/test_cli_routing.py::test_acp_new_clears_persisted_binding_before_next_session_load

[x] Permission broker wiring for trusted sessions
    Location: nanobot/acp/permissions.py:391-541
    Tests: tests/acp/test_cli_routing.py::test_trusted_telegram_auto_policy_resolves_without_prompting

[x] Update sink clearing between prompts
    Location: nanobot/acp/service.py:333-336
    Tests: tests/acp/test_cli_routing.py::test_acp_routing_clears_stale_update_subscription_when_progress_hidden

[x] Command menu registration with startup retry
    Location: nanobot/channels/telegram.py:201-229
    Tests: tests/test_telegram_channel.py::test_refresh_bot_commands_retries_until_acp_commands_appear

[x] Callback round-trip for permissions
    Location: nanobot/acp/sdk_client.py:688-769
    Tests: tests/acp/test_sdk_adapter.py::test_permission_decision_is_sent_back_over_sdk_connection

[x] Live filesystem/terminal handler registration
    Location: nanobot/cli/commands.py:76-82, nanobot/acp/service.py:338-378
    Tests: tests/acp/test_cli_routing.py::test_live_acp_service_registers_real_filesystem_and_terminal_handlers_before_prompting

[x] Metadata preservation on ACP responses
    Location: nanobot/agent/loop.py:868-881
    Tests: tests/acp/test_cli_routing.py::test_acp_routing_preserves_inbound_metadata_on_final_response

[x] Progress visibility independent of streaming flag
    Location: nanobot/agent/loop.py:252-289
    Tests: tests/acp/test_cli_routing.py::test_acp_routing_subscribes_to_visible_updates_without_live_content

[x] /stop cancels ACP operation
    Location: nanobot/agent/loop.py:487-491
    Tests: tests/acp/test_cli_routing.py::test_stop_cancels_acp_operation

[x] Channel/chat preservation in routing
    Location: nanobot/agent/loop.py:218-221
    Tests: tests/acp/test_cli_routing.py::test_acp_routing_preserves_telegram_channel

DIVERGENCES FOUND
-----------------

None. All features claimed in the plan are fully implemented and tested.

Added Beyond Plan
-----------------

[x] Terminal lifecycle callback error translation
    Location: nanobot/acp/sdk_client.py:1408-1500
    Tests: tests/acp/test_sdk_adapter.py::test_invalid_terminal_lifecycle_requests_raise_protocol_errors
    Rationale: Post-review hardening to prevent internal errors from surfacing to users

[x] Available commands caching from ACP updates
    Location: nanobot/acp/sdk_client.py:50-130
    Tests: tests/acp/test_sdk_adapter.py::test_handler_tracks_available_commands_updates
    Rationale: Needed to support command menu registration from ACP-advertised commands

VERIFICATION SUMMARY
--------------------

Behaviors Verified: 13/13 matched plan
Divergences Found: 0
Decisions Verified: 6/6 reflected in code
Added Beyond Plan: 2 (implementation details discovered during hardening)

Test Results:
- tests/test_telegram_channel.py: 15 passed
- tests/acp/test_cli_routing.py: 48 passed
- tests/acp/test_sdk_adapter.py: 40 passed, 3 skipped
- tests/acp/test_cron_acp.py: 20 passed
- Total ACP tests: 268 passed, 14 skipped
- ruff check: All checks passed

IMPLEMENTATION FILES CHECKED
----------------------------

Core Implementation:
- nanobot/channels/telegram.py (685 lines)
- nanobot/agent/loop.py (880 lines)
- nanobot/acp/service.py (442 lines)
- nanobot/acp/permissions.py (541 lines)
- nanobot/acp/sdk_client.py (1662 lines)
- nanobot/cli/commands.py (1003 lines)
- nanobot/acp/fs.py
- nanobot/acp/terminal.py

Tests:
- tests/test_telegram_channel.py
- tests/acp/test_cli_routing.py
- tests/acp/test_sdk_adapter.py
- tests/acp/test_cron_acp.py

RECOMMENDATION
--------------

Proceed with documenting ACTUAL implementation state. All plan features are
implemented and verified. The feature is ready for graduation to permanent
documentation.

================================================================================
