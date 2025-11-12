# Bugs

## DONE

- [x] .claude/hooks/notification.py hook does NOT send a notification to telegram

  [2025-11-12 02:04:00] **Fixed**: Updated `.claude/hooks/scripts/mcp_send.py` to perform proper MCP protocol initialization handshake (initialize → initialized → tools/call). Integration test added (`tests/integration/test_notification_hook.py`) to verify protocol works correctly.

- [x] pre-commit hook calls format which changes files, but this should NOT reject the commit

  [2025-11-12 01:57:31] **Fixed**: Added `pass_filenames: true` to pre-commit config and updated format.sh to accept file arguments.

- [x] user input & feedback messages below a message with a long running process are not collected and removed

  [2025-11-12 01:59:17] **Fixed**: Added `_pre_handle_user_input()` method to UiAdapter to cleanup feedback messages on user input.
