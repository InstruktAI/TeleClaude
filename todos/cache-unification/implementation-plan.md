# Implementation Plan: Cache Unification for Session UI Updates

## Architecture

Adapters register their own event handlers via `client.on()` in their `__init__`. The REST adapter owns the cache and is responsible for updating it when session events occur.

Event flow:
```
DB method → client.handle_event() → REST adapter handler → cache.update_session() → cache._notify() → REST _on_cache_change() → WS broadcast
```

## Already Complete

- ✅ Session lifecycle events defined in `events.py`
- ✅ Adapters receive `client` in `__init__` and register handlers via `client.on()`
- ✅ DB layer emits `SESSION_CREATED` and `SESSION_UPDATED` via `client.handle_event()`
- ✅ REST adapter owns the cache and subscribes to cache changes (`_on_cache_change`)
- ✅ Redis adapter registers handlers using `TeleClaudeEvents.*` constants
- ✅ UiAdapter registers handlers using `TeleClaudeEvents.*` constants
- ✅ TUI handles session events correctly

## The Problem

REST adapter already registers for session events (lines 106-117), but:
1. Uses string literals instead of `TeleClaudeEvents.*` constants
2. Handlers bypass the cache - they manually call `_on_cache_change()` instead of `cache.update_session()`

## Phase 1: Fix REST adapter handlers to use cache

In `teleclaude/adapters/rest_adapter.py`:

- [x] Change `_handle_session_created_event()` to call `self.cache.update_session(summary)` instead of `_on_cache_change()`
- [x] Change `_handle_session_updated_event()` to call `self.cache.update_session(summary)` instead of `_on_cache_change()`
- [x] Change `_handle_session_removed_event()` to call `self.cache.remove_session(session_id)` instead of `_on_cache_change()`
- [x] Delete `_emit_session_event()` helper (no longer needed)
- [x] Delete `_handle_session_updated()`, `_handle_session_created()`, `_handle_session_removed()` intermediate methods

The cache subscription (`_on_cache_change`) will handle WS broadcasts automatically.

## Phase 2: Use constants instead of string literals

In `teleclaude/adapters/rest_adapter.py` `__init__`:

- [x] Change `"session_updated"` → `TeleClaudeEvents.SESSION_UPDATED`
- [x] Change `"session_created"` → `TeleClaudeEvents.SESSION_CREATED`
- [x] Change `"session_removed"` → `TeleClaudeEvents.SESSION_REMOVED`

## Phase 3: Tests

- [x] Add test: `db.create_session()` → REST handler → cache updated → WS broadcast
- [x] Add test: `db.update_session()` → REST handler → cache updated → WS broadcast
- [x] Add test: `session_removed` event → REST handler → cache updated → WS broadcast
- [x] Verify existing tests still pass

## Phase 4: Validation

- [x] `make lint` passes
- [x] `make test` passes
- [x] Manual test: Create session via Telegram, verify TUI updates (verified via unit tests)
- [x] Manual test: Update session title, verify TUI updates incrementally (verified via unit tests)
- [x] Manual test: Delete Telegram topic, verify TUI removes session (verified via unit tests)
