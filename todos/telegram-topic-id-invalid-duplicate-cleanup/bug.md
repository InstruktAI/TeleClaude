# Bug: Telegram Topic_id_invalid delete failures are caused by duplicate session cleanup execution, not missing topic creation. Root cause timeline: end_session calls terminate_session and successfully deletes Telegram topic; db.close_session emits SESSION_CLOSED; daemon \_handle_session_closed calls terminate_session again; second delete attempts same topic and gets Topic_id_invalid. Maintenance periodic_cleanup also replays session_closed for all sessions closed within 12h, causing additional duplicate delete attempts after restart/hourly. Implement fix with exact constraints: (1) SESSION_CLOSED must be observer-only and MUST NOT trigger terminate_session side effects. (2) Introduce/route a single close-intent path (e.g., SESSION_CLOSE_REQUESTED) that performs termination exactly once per close intent. (3) Replace blind replay of closed sessions with replay of unresolved cleanup only (e.g., closed sessions whose Telegram topic reference still exists / unresolved channel cleanup), not every closed session in time window. (4) In Telegram delete, treat Topic_id_invalid as already-deleted success and log at debug/info, not warning. (5) On successful delete OR Topic_id_invalid, clear persisted telegram topic_id so reconciler does not retry indefinitely. (6) Add concurrency/idempotency guard so parallel/session-duplicate events cannot run destructive cleanup twice for same session. Required tests: end_session path does not produce second terminate pass; session_closed observer path does not re-delete channels; maintenance replay skips fully-cleaned closed sessions; Topic_id_invalid path is non-warning and marks topic as cleared; cleanup remains eventual for true missed deletions. Keep behavior safe for restart recovery and for genuinely missed cleanup.

## Symptom

Telegram Topic_id_invalid delete failures are caused by duplicate session cleanup execution, not missing topic creation. Root cause timeline: end_session calls terminate_session and successfully deletes Telegram topic; db.close_session emits SESSION_CLOSED; daemon \_handle_session_closed calls terminate_session again; second delete attempts same topic and gets Topic_id_invalid. Maintenance periodic_cleanup also replays session_closed for all sessions closed within 12h, causing additional duplicate delete attempts after restart/hourly. Implement fix with exact constraints: (1) SESSION_CLOSED must be observer-only and MUST NOT trigger terminate_session side effects. (2) Introduce/route a single close-intent path (e.g., SESSION_CLOSE_REQUESTED) that performs termination exactly once per close intent. (3) Replace blind replay of closed sessions with replay of unresolved cleanup only (e.g., closed sessions whose Telegram topic reference still exists / unresolved channel cleanup), not every closed session in time window. (4) In Telegram delete, treat Topic_id_invalid as already-deleted success and log at debug/info, not warning. (5) On successful delete OR Topic_id_invalid, clear persisted telegram topic_id so reconciler does not retry indefinitely. (6) Add concurrency/idempotency guard so parallel/session-duplicate events cannot run destructive cleanup twice for same session. Required tests: end_session path does not produce second terminate pass; session_closed observer path does not re-delete channels; maintenance replay skips fully-cleaned closed sessions; Topic_id_invalid path is non-warning and marks topic as cleared; cleanup remains eventual for true missed deletions. Keep behavior safe for restart recovery and for genuinely missed cleanup.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-26

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
