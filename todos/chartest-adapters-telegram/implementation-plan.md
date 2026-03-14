# Implementation Plan: chartest-adapters-telegram

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/adapters/telegram_adapter.py` → `tests/unit/adapters/test_telegram_adapter.py`
- [ ] Characterize `teleclaude/adapters/telegram/callback_handlers.py` → `tests/unit/adapters/telegram/test_callback_handlers.py`
- [ ] Characterize `teleclaude/adapters/telegram/channel_ops.py` → `tests/unit/adapters/telegram/test_channel_ops.py`
- [ ] Characterize `teleclaude/adapters/telegram/input_handlers.py` → `tests/unit/adapters/telegram/test_input_handlers.py`
- [ ] Characterize `teleclaude/adapters/telegram/message_ops.py` → `tests/unit/adapters/telegram/test_message_ops.py`
- [ ] Characterize `teleclaude/adapters/telegram/private_handlers.py` → `tests/unit/adapters/telegram/test_private_handlers.py`
