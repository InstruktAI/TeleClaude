# Review Findings: telegram-topic-id-invalid-duplicate-cleanup

## Verdict: APPROVE

---

## Summary

Fix correctly addresses all 6 constraints from bug.md. The intent/fact separation, concurrency guard, idempotent cleanup, and maintenance replay filter are all sound. Test coverage is adequate for the key contracts. Important findings below are robustness improvements, not correctness defects.

---

## Paradigm-Fit Assessment

- **Data flow**: DB access in `channel_ops.py` uses the established `db` singleton. Session metadata mutation follows existing patterns (`get_metadata().get_ui().get_telegram()`). No bypasses.
- **Event system**: New `SESSION_CLOSE_REQUESTED` event follows the existing `TeleClaudeEvents` class and auto-registration pattern in `daemon.py:322–346`. No explicit subscription needed.
- **Pattern consistency**: Handler naming (`_handle_session_close_requested`) matches convention and auto-discovery picks it up correctly. Concurrency guard pattern (module-level set with `finally`-based cleanup) is consistent with Python asyncio idioms.

No paradigm violations found.

---

## Constraint Verification

| Constraint                                        | Status | Evidence                                                                                                    |
| ------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------- |
| (1) SESSION_CLOSED observer-only                  | ✅     | `_handle_session_closed` removes in-memory state only; no `terminate_session` call                          |
| (2) SESSION_CLOSE_REQUESTED single terminate path | ✅     | New handler + event; `_handle_topic_closed` now emits intent, not fact                                      |
| (3) Replay of unresolved cleanup only             | ✅     | `emit_recently_closed_session_events` filters by `telegram_topic_id is None and discord_channel_id is None` |
| (4) Topic_id_invalid = success, log at info       | ✅     | `BadRequest` caught, `"topic_id_invalid" in str(e).lower()` check, `logger.info(...)`                       |
| (5) Clear topic_id on success OR invalid          | ✅     | DB cleared via `db.update_session` after both paths                                                         |
| (6) Concurrency guard                             | ✅     | `_cleanup_in_flight: set[str]` at module level, guarded in `terminate_session` with `finally`               |

---

## Critical

None.

---

## Important

### 1. `db.update_session` exception can escape `delete_channel` and disrupt cleanup chain

**File:** `teleclaude/adapters/telegram/channel_ops.py:235–242`

After the Telegram topic is successfully deleted (or `Topic_id_invalid` treated as success), the code fetches a fresh session and calls `db.update_session` to clear `topic_id`. If `db.update_session` raises (e.g., transient DB error), the exception propagates out of `delete_channel` into `cleanup_session_resources` → `_terminate_session_inner`. Depending on how `cleanup_session_resources` handles exceptions from `delete_channel`, subsequent cleanup steps (tmux kill, `db.close_session`) may not execute.

The channel deletion itself was already successful at this point, so surfacing an exception is misleading. The DB update failure should be logged as a warning and the function should still return `True` — maintenance replay will retry and clear the topic_id on the next pass.

```python
# Current — exception can escape:
await db.update_session(session.session_id, adapter_metadata=fresh_session.adapter_metadata)
```

Recommended fix: wrap the DB update in try/except with a warning log, return `True` regardless.

### 2. No explicit integration test for the primary root-cause scenario

**File:** `tests/integration/test_session_lifecycle.py`

Bug.md explicitly required "end_session path does not produce second terminate pass". The existing test `test_session_closed_event_is_observer_only` verifies that SESSION_CLOSED doesn't trigger `delete_channel`, which covers the key contract. However, no test exercises the full end-to-end chain:

```
end_session API → terminate_session → db.close_session → SESSION_CLOSED → _handle_session_closed (observer-only) → no second delete_channel
```

This is the exact failure path from the bug report. A direct regression test for this path would make the fix self-documenting and prevent future regressions at the source.

---

## Suggestions

### 1. String match for `topic_id_invalid` is fragile

**File:** `teleclaude/adapters/telegram/channel_ops.py:220`

```python
if "topic_id_invalid" in str(e).lower():
```

Telegram API error messages can change. Consider extracting this to a named constant:

```python
_TOPIC_ALREADY_DELETED_MSG = "topic_id_invalid"
```

Makes the intent discoverable and centralizes the string for updates.

### 2. `_cleanup_in_flight` is process-local

**File:** `teleclaude/core/session_cleanup.py:121`

The module-level set is correct for single-process asyncio. A brief comment clarifying "process-local; not shared across daemon restarts" would help future maintainers understand the scope and why restart recovery is handled by the maintenance replay mechanism rather than this guard.

---

## Why No Additional Issues

- Copy-paste duplication checked: `_handle_session_close_requested` is a net-new handler, not a copy of `_handle_session_closed`.
- DB clearing pattern (fetch-fresh → mutate → update) is consistent with existing adapter metadata mutation patterns.
- Test `test_session_close_requested_concurrent_is_idempotent` correctly races two events before `await` and verifies `assert_called_once()`.
- `emit_recently_closed_session_events` correctly covers both Telegram and Discord channel references in the filter condition.
- Auto-subscription confirms `SESSION_CLOSE_REQUESTED` handler is registered without any manual wiring needed.
