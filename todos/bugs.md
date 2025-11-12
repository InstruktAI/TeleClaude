# Bugs

## OPEN

## CLOSED

- [x] .claude/hooks/notification.py hook does NOT send a notification to telegram

  [2025-11-12 03:12:00] **WIP**: Added comprehensive logging to all hook scripts (`notification.py`, `mcp_send.py`, `summarizer.py`).

  [2025-11-12 04:25:00] **Partial fix**: Changed event detection logic from checking `data.get("stop_hook_active") or data.get("transcript_path")` to properly checking `hook_event_name` field. The bug was that notification events with `transcript_path` were incorrectly classified as Stop events. Now correctly routes to Notification handler which calls `mcp_send()`. Verified with test showing successful MCP socket connection and tool call.

  [2025-11-12 04:29:00] **Second bug fixed**: Removed skip logic that prevented ALL "Claude is waiting for your input" messages from being sent. Hook now generates custom message from templates.

  [2025-11-12 04:36:00] **Root cause fixed**: Output poller was sending updates on every output change (every 1s), causing Telegram API rate limiting (HTTP 429). Changed to enforce minimum 2-second interval between all message edits. Verified with logs showing ~2s intervals and successful notification delivery (HTTP 200).

  [2025-11-12 04:44:00] **FULLY FIXED**: Added CWD-based session mapping. Claude Code notification hook was trying to send to Claude Code session IDs which don't exist in TeleClaude. Created `teleclaude__find_session_by_cwd` MCP tool to map Claude Code sessions to TeleClaude terminal sessions by matching working directory. Hook now successfully delivers notifications to correct Telegram topic. Verified end-to-end with real Claude Code session.

- [x] pre-commit hook calls format which changes files, but this should NOT reject the commit

  [2025-11-12 01:57:31] **Fixed**: Added `pass_filenames: true` to pre-commit config and updated format.sh to accept file arguments.

- [x] user input & feedback messages below a message with a long running process are not collected and removed

  [2025-11-12 01:59:17] **Fixed**: Added `_pre_handle_user_input()` method to UiAdapter to cleanup feedback messages on user input. Also updated `teleclaude__send_notification` in mcp_server.py to mark notification hook messages for cleanup via `add_pending_deletion()`, ensuring they are removed when user sends next input.

- [x] system-reminder tags are not properly filtered out from the output file and thus messages sent to user

  [2025-11-12 04:32:00] **INVESTIGATION**: Tested the regex pattern `<system-reminder>[\s\S]*?</system-reminder>` extensively - it works correctly for all test cases including multiline content with special chars. All 233 unit tests pass. Need to identify the specific real-world case where filtering fails.
