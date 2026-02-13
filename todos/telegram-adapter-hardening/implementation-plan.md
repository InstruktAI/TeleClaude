# Implementation Plan - Telegram Adapter Hardening

The goal is to harden the Telegram adapter architecture by enforcing deterministic routing via the database, removing brittle regex-based ownership inference, and improving encapsulation.

## User Review Required

> [!IMPORTANT]
> **Critical Change:** We are replacing the regex-based "topic ownership" check (`_topic_owned_by_this_bot`) with a strict DB lookup (`db.get_sessions_by_adapter_metadata`).
>
> **Impact:**
>
> - If a topic ID is not in the DB, the message is ignored. No more "guessing" if it belongs to us.
> - "Orphan" topics (valid ID format but not in DB) will be treated as noise and ignored, NOT deleted. The previous reactive deletion logic was dangerous and noisy.
> - **Action Required:** Ensure the database is the single source of truth for all active sessions.

- [x] **Confirm:** "Ignore" strategy for unknown topics is acceptable (vs "Delete").
- [x] **Confirm:** Law of Demeter enforcement (`session.get_metadata().get_ui().get_telegram()` and `session.get_metadata().get_transport().get_redis()`) is desired.

## Proposed Changes

### 1. Unified Routing Lane (`adapter_client.py`)

- [x] Refactor `send_message` to use `_route_to_ui` for all UI-bound messages (not just errors).
- [x] Ensure `_route_to_ui` uses the encapsulated metadata accessor.

### 2. Encapsulation & Law of Demeter (`models.py`)

- [x] Define `UiAdapterMetadata` in `teleclaude/core/models.py`.
- [x] Define `TransportAdapterMetadata` in `teleclaude/core/models.py` (for Redis encapsulation).
- [x] Update `SessionAdapterMetadata` to hold `_ui` (UiAdapterMetadata) and `_transport` (TransportAdapterMetadata) instead of raw `telegram`/`redis` dicts.
- [x] Expose `get_ui()` and `get_transport()` methods.
- [x] Maintain JSON serialization compatibility (flatten/unflatten).

### 3. Strict Ownership & Sane Routing (`telegram_adapter.py`)

- [x] Remove `_topic_title_mentions_this_computer` (regex logic).
- [x] Remove `_topic_owned_by_this_bot` (regex logic).
- [x] Update `_get_session_from_topic`:
  - Query DB via `db.get_sessions_by_adapter_metadata(adapter="telegram", key="topic_id", value=topic_id)`.
  - If DB returns match -> Process.
  - If DB returns empty -> Ignore (log as trace/debug).
- [x] Remove `_delete_orphan_topic` calls entirely.

### 4. Normalize Delivery Contract (`message_ops.py`)

- [x] Update `send_message` and `send_file` to:
  - Check `metadata.topic_id` immediately.
  - Raise `RuntimeError("Telegram topic_id missing")` if absent (Fail Fast).
  - Return `message_id` on success.

## Verification Plan

### Automated Tests

- [x] Run `tests/unit/test_telegram_adapter.py` to verify routing logic.
- [x] Run `tests/unit/test_adapter_client.py` to verify unified sending path.
- [x] Run `tests/unit/test_db.py` to verify metadata queries.
- [x] Run `tests/unit/test_redis_adapter.py` to verify transport metadata encapsulation.

### Manual Verification (if needed)

- [x] Start daemon.
- [x] Send message to known session -> delivered.
- [x] Send message to random topic -> ignored (no log spam).
- [x] Verify TUI updates correctly.

## Status

- **Status:** Complete
- **Started:** 2026-02-13
- **Completed:** 2026-02-13
