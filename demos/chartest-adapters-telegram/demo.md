# Demo: chartest-adapters-telegram

## Validation

```bash
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/chartest-adapters-telegram
. .venv/bin/activate && pytest tests/unit/adapters/ -q --timeout=10
```

## Guided Presentation

The characterization tests for the Telegram adapter are run to verify all 128 tests pass.

The tests cover:

- `telegram_adapter.py` — class constants and helper methods plus `_pre_handle_user_input` / `_post_handle_user_input` cleanup tracking
- `callback_handlers.py` — CallbackAction enum values, full LEGACY_ACTION_MAP matrix, and `_handle_callback_query` dispatch routing
- `channel_ops.py` — topic readiness timeout handling plus create/update/close/reopen/delete channel behavior
- `input_handlers.py` — IncomingFileType enum, FILE_SUBDIR mapping, helper describers, and `_handle_help` routing
- `message_ops.py` — EditContext dataclass, `_content_hash`, `_truncate_for_platform`, `send_message` reflection behavior, and pending-edit updates
- `private_handlers.py` — `_register_simple_command_handlers`, `_handle_private_start`, `_handle_private_text`, `_handle_simple_command`, and delete_message routing
