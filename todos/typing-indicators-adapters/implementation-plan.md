# Implementation Plan: typing-indicators-adapters

## Overview

Wire the existing `typing_callback` hook in `InboundQueueManager` to call platform-native typing indicators on the originating adapter immediately after message enqueue. No adapter refactoring needed — the hook infrastructure exists, it just needs to be connected.

## Tasks

### Task 1: Implement `typing_indicator_callback` in `command_handlers.py`

**File:** `teleclaude/core/command_handlers.py`

Add a new async function alongside `deliver_inbound`:

```python
async def typing_indicator_callback(
    session_id: str, origin: str, *, client: AdapterClient
) -> None:
    """Fire typing indicator on the adapter matching the message origin."""
    _TYPING_ORIGINS = {"telegram", "discord", "whatsapp"}
    if origin not in _TYPING_ORIGINS:
        return
    adapter = client.adapters.get(origin)
    if adapter is None or not isinstance(adapter, UiAdapter):
        return
    session = db.get_session(session_id)
    if session is None:
        return
    await adapter.send_typing_indicator(session)
```

Key design decisions:
- Filter by origin first (cheap) before any DB lookup.
- Use `client.adapters.get(origin)` — origin string matches adapter registration key.
- Session lookup uses the existing `db.get_session()`.
- No try/except here — the caller (`InboundQueueManager.enqueue`) already wraps in try/except.

### Task 2: Wire the callback in `CommandService.__init__`

**File:** `teleclaude/core/command_service.py`

Change the `init_inbound_queue_manager` call to pass the typing callback:

```python
init_inbound_queue_manager(
    functools.partial(deliver_inbound, client=client, start_polling=start_polling),
    typing_callback=functools.partial(typing_indicator_callback, client=client),
    force=True,
)
```

This partial binds `client` so the callback signature matches `TypingCallback = Callable[[str, str], Awaitable[None]]`.

Import `typing_indicator_callback` from `command_handlers`.

### Task 3: Add unit tests

**File:** `tests/unit/test_inbound_queue.py` (existing file, add test cases)

Tests to add:

1. **`test_typing_callback_fires_on_successful_enqueue`**: Mock the typing callback, enqueue a message, verify callback was called with `(session_id, origin)`.

2. **`test_typing_callback_not_called_on_duplicate`**: Enqueue same message twice (same `source_message_id`), verify callback called exactly once.

3. **`test_typing_callback_exception_does_not_block_enqueue`**: Set callback to raise, verify enqueue still returns row_id successfully.

**File:** `tests/unit/test_typing_indicator_callback.py` (new file)

Tests for the callback function itself:

4. **`test_typing_fires_on_telegram_origin`**: Mock adapter client with telegram adapter, verify `send_typing_indicator` called.

5. **`test_typing_fires_on_discord_origin`**: Same for discord.

6. **`test_typing_fires_on_whatsapp_origin`**: Same for whatsapp.

7. **`test_typing_skipped_for_non_ui_origins`**: Origin `"api"`, `"terminal"`, `"redis"`, `"hook"` — verify no adapter interaction.

8. **`test_typing_skipped_when_adapter_not_registered`**: Origin `"telegram"` but no telegram adapter registered — verify graceful no-op.

9. **`test_typing_skipped_when_session_not_found`**: Valid origin and adapter but session_id not in DB — verify graceful no-op.

## File Change Summary

| File | Change |
|------|--------|
| `teleclaude/core/command_handlers.py` | Add `typing_indicator_callback` function |
| `teleclaude/core/command_service.py` | Wire `typing_callback` parameter, add import |
| `tests/unit/test_inbound_queue.py` | Add 3 test cases for callback integration |
| `tests/unit/test_typing_indicator_callback.py` | New file: 6 test cases for callback logic |

## Verification

1. Run `pytest tests/unit/test_inbound_queue.py tests/unit/test_typing_indicator_callback.py -v`
2. Run full test suite: `pytest tests/ -x --timeout=30`
3. Manual: send a message in Telegram/Discord, observe typing indicator appears before agent response.

## Risks

- **Low risk:** The `typing_callback` hook is already called inside a try/except in `enqueue()`. Even a buggy callback cannot break message delivery.
- **Low risk:** `db.get_session()` is a synchronous DB read, fast and well-tested.
- **No risk to existing typing:** The `_dispatch_command` typing indicator in `ui_adapter.py` is independent and continues to work (it signals "agent processing", not "message received").
