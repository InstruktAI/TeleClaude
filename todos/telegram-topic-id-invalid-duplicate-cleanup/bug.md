# Bug: Telegram Topic_id_invalid delete failures are caused by duplicate session cleanup execution, not missing topic creation. Root cause timeline: end_session calls terminate_session and successfully deletes Telegram topic; db.close_session emits SESSION_CLOSED; daemon \_handle_session_closed calls terminate_session again; second delete attempts same topic and gets Topic_id_invalid. Maintenance periodic_cleanup also replays session_closed for all sessions closed within 12h, causing additional duplicate delete attempts after restart/hourly. Implement fix with exact constraints: (1) SESSION_CLOSED must be observer-only and MUST NOT trigger terminate_session side effects. (2) Introduce/route a single close-intent path (e.g., SESSION_CLOSE_REQUESTED) that performs termination exactly once per close intent. (3) Replace blind replay of closed sessions with replay of unresolved cleanup only (e.g., closed sessions whose Telegram topic reference still exists / unresolved channel cleanup), not every closed session in time window. (4) In Telegram delete, treat Topic_id_invalid as already-deleted success and log at debug/info, not warning. (5) On successful delete OR Topic_id_invalid, clear persisted telegram topic_id so reconciler does not retry indefinitely. (6) Add concurrency/idempotency guard so parallel/session-duplicate events cannot run destructive cleanup twice for same session. Required tests: end_session path does not produce second terminate pass; session_closed observer path does not re-delete channels; maintenance replay skips fully-cleaned closed sessions; Topic_id_invalid path is non-warning and marks topic as cleared; cleanup remains eventual for true missed deletions. Keep behavior safe for restart recovery and for genuinely missed cleanup.

## Symptom

Telegram Topic_id_invalid delete failures are caused by duplicate session cleanup execution, not missing topic creation. Root cause timeline: end_session calls terminate_session and successfully deletes Telegram topic; db.close_session emits SESSION_CLOSED; daemon \_handle_session_closed calls terminate_session again; second delete attempts same topic and gets Topic_id_invalid. Maintenance periodic_cleanup also replays session_closed for all sessions closed within 12h, causing additional duplicate delete attempts after restart/hourly. Implement fix with exact constraints: (1) SESSION_CLOSED must be observer-only and MUST NOT trigger terminate_session side effects. (2) Introduce/route a single close-intent path (e.g., SESSION_CLOSE_REQUESTED) that performs termination exactly once per close intent. (3) Replace blind replay of closed sessions with replay of unresolved cleanup only (e.g., closed sessions whose Telegram topic reference still exists / unresolved channel cleanup), not every closed session in time window. (4) In Telegram delete, treat Topic_id_invalid as already-deleted success and log at debug/info, not warning. (5) On successful delete OR Topic_id_invalid, clear persisted telegram topic_id so reconciler does not retry indefinitely. (6) Add concurrency/idempotency guard so parallel/session-duplicate events cannot run destructive cleanup twice for same session. Required tests: end_session path does not produce second terminate pass; session_closed observer path does not re-delete channels; maintenance replay skips fully-cleaned closed sessions; Topic_id_invalid path is non-warning and marks topic as cleared; cleanup remains eventual for true missed deletions. Keep behavior safe for restart recovery and for genuinely missed cleanup.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-26

## Investigation

Traced the execution paths through daemon.py, session_cleanup.py, command_handlers.py, and channel_ops.py.

**Path 1 — `end_session` API call:**

1. `end_session` (command_handlers.py:1556) calls `terminate_session(reason="end_session")`
2. `terminate_session` calls `cleanup_session_resources` → `adapter_client.delete_channel(session)` → **Telegram topic deleted**
3. `terminate_session` calls `db.close_session(session_id)`
4. `db.close_session` (db.py:705) emits `SESSION_CLOSED` via `event_bus.emit`
5. `_handle_session_closed` (daemon.py:1072) receives the event
6. `_handle_session_closed` calls `terminate_session` again (the bug!)
7. Second `terminate_session` → `cleanup_session_resources` → `delete_channel` → **`Topic_id_invalid`**

**Path 2 — Maintenance replay (`emit_recently_closed_session_events`):**

- Called hourly and on startup from `MaintenanceService.periodic_cleanup`
- Replays `SESSION_CLOSED` for ALL sessions closed within 12 hours (regardless of cleanup state)
- Each replay re-triggers `_handle_session_closed` → `terminate_session` → duplicate delete

**Path 3 — Telegram topic closed externally:**

- `_handle_topic_closed` emits `SESSION_CLOSED` for active session
- `_handle_session_closed` calls `terminate_session`
- `terminate_session` → `db.close_session` → emits `SESSION_CLOSED` again → second invocation

## Root Cause

`SESSION_CLOSED` was used as both an "intent" (trigger cleanup) and a "fact" (session is now closed). The `_handle_session_closed` daemon handler called `terminate_session` on every `SESSION_CLOSED` event, even when the event was emitted _by_ `terminate_session` itself (via `db.close_session`). This created a self-reinforcing loop that attempted to delete the Telegram topic multiple times.

Secondary root causes:

- `emit_recently_closed_session_events` replayed `SESSION_CLOSED` for ALL recently-closed sessions, not just those with pending cleanup
- `delete_channel` did not clear `topic_id` from DB after success, so the reconciler kept retrying
- `Topic_id_invalid` was logged as a warning instead of treated as already-deleted success
- No concurrency guard prevented parallel terminate calls for the same session

## Fix Applied

**1. SESSION_CLOSED made observer-only** (`daemon.py`):

- `_handle_session_closed` now only cleans in-memory state (queues, workers, codex state)
- It no longer calls `terminate_session`

**2. New `SESSION_CLOSE_REQUESTED` intent event** (`events.py`, `daemon.py`):

- Added `SESSION_CLOSE_REQUESTED` to `EventType` and `TeleClaudeEvents`
- New `_handle_session_close_requested` handler calls `terminate_session` exactly once
- `_handle_topic_closed` (input_handlers.py) now emits `SESSION_CLOSE_REQUESTED` for active sessions (was `SESSION_CLOSED`)

**3. Maintenance replay: unresolved cleanup only** (`session_cleanup.py`):

- `emit_recently_closed_session_events` now filters to sessions with `topic_id` or `discord.channel_id` still set
- Emits `SESSION_CLOSE_REQUESTED` (not `SESSION_CLOSED`) for those sessions

**4+5. `Topic_id_invalid` = success + clear topic_id** (`channel_ops.py`):

- `BadRequest("Topic_id_invalid")` caught and treated as already-deleted success
- Logged at info level (not warning)
- On success OR Topic_id_invalid: fetches fresh session and clears `topic_id` in DB
- Prevents maintenance replay from retrying completed cleanup

**6. Concurrency guard** (`session_cleanup.py`):

- Module-level `_cleanup_in_flight: set[str]` tracks in-progress cleanups
- `terminate_session` wraps inner logic: concurrent calls for same session return `False` immediately
- Sequential calls (after first completes) still work via the topic_id clear mechanism
