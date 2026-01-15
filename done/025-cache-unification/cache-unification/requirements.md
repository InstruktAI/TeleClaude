# Requirements: Cache Unification for Session UI Updates

## Objective

Make the cache the sole source of truth for session list updates in the UI. WebSocket updates must be derived from cache mutations, not bypass them.

## Current State

The following are already implemented:
- Session lifecycle events defined in `events.py`
- Adapters register handlers via `client.on()` in their `__init__`
- DB layer emits events on `create_session()` and `update_session()`
- REST adapter owns the cache and subscribes to cache changes for WS broadcasts
- Redis adapter and UiAdapter use `TeleClaudeEvents.*` constants
- TUI correctly handles incremental updates vs full refresh

## The Problem

REST adapter registers for session events but bypasses the cache:
- Handlers call `_on_cache_change()` directly instead of `cache.update_session()`
- Uses string literals instead of `TeleClaudeEvents.*` constants

## Remaining Work

### O1: REST adapter handlers must update cache

Change handlers to call `cache.update_session()` / `cache.remove_session()` instead of bypassing.
Cache notification via `_on_cache_change()` will handle WS broadcasts automatically.

### O2: Use event constants

Change string literals to `TeleClaudeEvents.*` constants for consistency with other adapters.

## Acceptance Criteria

- [x] Session lifecycle events defined in `events.py`
- [x] Adapters register handlers via `client.on()`
- [x] Remote sessions update cache and trigger WS broadcasts
- [x] TUI handles events correctly
- [x] REST adapter handlers update cache (not bypass it)
- [x] REST adapter uses `TeleClaudeEvents.*` constants
- [x] Tests cover local session lifecycle → cache → WS flow
- [x] Lint passes
