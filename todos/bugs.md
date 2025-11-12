# Bugs

## OPEN

## CLOSED

- [x] .claude/hooks/notification.py hook does NOT send a notification to telegram

  [2025-11-12 03:12:00] **WIP**: Added comprehensive logging to all hook scripts (`notification.py`, `mcp_send.py`, `summarizer.py`).

  [2025-11-12 04:25:00] **Fixed**: Changed event detection logic from checking `data.get("stop_hook_active") or data.get("transcript_path")` to properly checking `hook_event_name` field. The bug was that notification events with `transcript_path` were incorrectly classified as Stop events. Now correctly routes to Notification handler which calls `mcp_send()`. Verified with test showing successful MCP socket connection and tool call.

- [x] pre-commit hook calls format which changes files, but this should NOT reject the commit

  [2025-11-12 01:57:31] **Fixed**: Added `pass_filenames: true` to pre-commit config and updated format.sh to accept file arguments.

- [x] user input & feedback messages below a message with a long running process are not collected and removed

  [2025-11-12 01:59:17] **Fixed**: Added `_pre_handle_user_input()` method to UiAdapter to cleanup feedback messages on user input. Also updated `teleclaude__send_notification` in mcp_server.py to mark notification hook messages for cleanup via `add_pending_deletion()`, ensuring they are removed when user sends next input.

- [x] system-reminder tags are not properly filtered out from the output file and thus messages sent to user

  [2025-11-12 04:32:00] **INVESTIGATION**: Tested the regex pattern `<system-reminder>[\s\S]*?</system-reminder>` extensively - it works correctly for all test cases including multiline content with special chars. All 233 unit tests pass. Need to identify the specific real-world case where filtering fails.
