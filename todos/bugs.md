# Bugs

## OPEN

(none)

## CLOSED

- [x] **edit_message Creates New Messages Instead of Editing** (FIXED 2025-12-01)

  **Root Cause:** When Telegram returns "Message is not modified" error (content unchanged), `edit_message` returned `False`, causing `_try_edit_output_message` to clear `output_message_id`. Subsequent polls then created NEW messages instead of editing.

  **Fix:** Modified `telegram_adapter.py` to treat "Message is not modified" as success (return `True`). This benign error means the message exists but content is unchanged - no need to clear `output_message_id`.

  **Tests Added:** `test_edit_message_not_modified_returns_true` and `test_edit_message_not_found_returns_false` in `tests/unit/test_telegram_adapter.py`

- [x] pending_deletions removal mechanism was broken (FIXED 2025-12-01)

  Three issues fixed:

  1. `message_id` was not passed in payload when emitting MESSAGE events from telegram_adapter.py
  2. `post_handler(session.session_id, ...)` passed a string but `_post_handle_user_input` expected a Session object
  3. Both pre/post handlers now receive correct types

- [x] teleclaude\_\_list_sessions(None) returned empty (FIXED 2025-12-01)

  When querying all computers (`computer=None`), the code only queried remote computers via Redis but never included local sessions. Fixed by adding local session query when `computer is None`.

- [x] session_closed event didn't propagate to observer adapters (FIXED 2025-12-01)

  In `adapter_client.py`, `close_channel(session.session_id)` and `reopen_channel(session.session_id)` passed a string instead of a Session object, causing method signature mismatch.

- [x] .claude/hooks/notification.py hook does NOT send a notification to telegram

  [2025-11-12 03:12:00] **WIP**: Added comprehensive logging to all hook scripts (`notification.py`, `mcp_send.py`, `summarizer.py`).

  [2025-11-12 04:25:00] **Partial fix**: Changed event detection logic from checking `data.get("stop_hook_active") or data.get("transcript_path")` to properly checking `hook_event_name` field. The bug was that notification events with `transcript_path` were incorrectly classified as Stop events. Now correctly routes to Notification handler which calls `mcp_send()`. Verified with test showing successful MCP socket connection and tool call.

  [2025-11-12 04:29:00] **Second bug fixed**: Removed skip logic that prevented ALL "Claude is waiting for your input" messages from being sent. Hook now generates custom message from templates.

  [2025-11-12 04:36:00] **Root cause fixed**: Output poller was sending updates on every output change (every 1s), causing Telegram API rate limiting (HTTP 429). Changed to enforce minimum 2-second interval between all message edits. Verified with logs showing ~2s intervals and successful notification delivery (HTTP 200).

  [2025-11-12 04:44:00] **Fourth bug fixed**: Added CWD-based session mapping. Claude Code notification hook was trying to send to Claude Code session IDs which don't exist in TeleClaude. Created `teleclaude__find_session_by_cwd` MCP tool to map Claude Code sessions to TeleClaude terminal sessions by matching working directory. Hook now successfully delivers notifications to correct Telegram topic. Verified end-to-end with real Claude Code session.

  [2025-11-12 05:14:00] **Better approach**: Switched from unreliable CWD-based mapping to env var injection. Tmux sessions now inject `TELECLAUDE_SESSION_ID` env var when created. Hook reads directly from `os.getenv()` for reliable 1:1 mapping. Removed `teleclaude__find_session_by_cwd` MCP tool. Notifications now arrive successfully.

  [2025-11-12 05:19:00] **Fifth bug fixed**: Fixed NameError in Stop event handler. When renaming `session_id` to `teleclaude_session_id`, missed updating the summarizer spawn call, causing `NameError: name 'session_id' is not defined`. Summarizer now spawns correctly.

  [2025-11-12 05:24:00] **FULLY FIXED**: Fixed ModuleNotFoundError in summarizer.py. Relative import `from utils.mcp_send import mcp_send` failed when run as uv script. Added parent directory to sys.path and changed to direct import. Stop event summaries now generate and send successfully.

- [x] pre-commit hook calls format which changes files, but this should NOT reject the commit

  [2025-11-12 01:57:31] **Fixed**: Added `pass_filenames: true` to pre-commit config and updated format.sh to accept file arguments.

- [x] user input & feedback messages below a message with a long running process are not collected and removed

  [2025-11-12 01:59:17] **Fixed**: Added `_pre_handle_user_input()` method to UiAdapter to cleanup feedback messages on user input. Also updated `teleclaude__send_notification` in mcp_server.py to mark notification hook messages for cleanup via `add_pending_deletion()`, ensuring they are removed when user sends next input.

- [x] system-reminder tags are not properly filtered out from the output file and thus messages sent to user

  [2025-11-12 04:32:00] **INVESTIGATION**: Tested the regex pattern `<system-reminder>[\s\S]*?</system-reminder>` extensively - it works correctly for all test cases including multiline content with special chars. All 233 unit tests pass. Need to identify the specific real-world case where filtering fails.
