# Review Findings: ucap-truthful-session-status

**Reviewer:** Claude (automated)
**Review round:** 1
**Baseline commit:** 76ce6dab
**Verdict:** REQUEST CHANGES

---

## Critical

### C1. Stall tasks not cancelled on session close

**File:** `teleclaude/core/agent_coordinator.py:468-499`, `teleclaude/daemon.py:1252-1280`

`_stall_tasks` are never cancelled when a session closes. `_handle_session_closed` in `daemon.py` calls `session_cleanup.terminate_session()` but never calls `coordinator._cancel_stall_task(session_id)`. The async stall watcher continues sleeping and will emit `awaiting_output` and `stalled` status events for a session that is already closed. These spurious events reach WS broadcast and Discord/Telegram handlers, which attempt DB lookups and message edits against a dead session. The `closed` status event emitted by `api_server._handle_session_closed_event` races with the stale stall events — clients receive contradictory status updates.

**Fix:** Cancel stall tasks on session close. Either subscribe `coordinator._cancel_stall_task` to `TeleClaudeEvents.SESSION_CLOSED`, or add explicit cleanup in `_handle_session_closed`.

### C2. Stall tasks not cancelled on agent error

**File:** `teleclaude/daemon.py:992-1005`, `teleclaude/core/agent_coordinator.py`

`AGENT_ERROR` is handled in `daemon.py` before reaching `coordinator.handle_event()`. The error path emits `TeleClaudeEvents.ERROR` directly but never calls `_cancel_stall_task`. Additionally, no canonical `error` status event is emitted — the status vocabulary includes `error` but the error path is silent for status consumers. After an `AGENT_ERROR`, clients will see `stalled` instead of `error`.

**Fix:** In the `AGENT_ERROR` branch, cancel the stall task and emit a canonical `error` status event.

### C3. `status_message_id` not deserialized in `from_json()`

**File:** `teleclaude/core/models.py:315-324`

`DiscordAdapterMetadata.status_message_id` is correctly serialized via `asdict_exclude_none()` in `to_json()`, but `from_json()` at lines 315-324 does not read it back. After a daemon restart, `status_message_id` is always `None`, causing `_handle_session_status` to post a new Discord message instead of editing the existing one — creating duplicate status messages for every transition.

**Fix:** Add deserialization analogous to `output_message_id`:

```python
raw_status_msg = discord_raw.get("status_message_id")
discord_status_message_id = str(raw_status_msg) if raw_status_msg is not None else None
```

Pass `status_message_id=discord_status_message_id` to the `DiscordAdapterMetadata` constructor.

---

## Important

### I1. `_handle_session_closed_event` bypasses contract validation

**File:** `teleclaude/api_server.py:257-277`

This is the only place that constructs `SessionLifecycleStatusEventDTO` directly without routing through `status_contract.serialize_status_event()`. All other status transitions go through the canonical serializer/validator. If the contract evolves (e.g., required fields change), this path will silently diverge. The inline `from datetime import datetime, timezone` is also inconsistent with the rest of the codebase.

**Fix:** Route the closed status emission through the coordinator's `_emit_status_event` (preferred — also solves C1), or at minimum call `serialize_status_event()` for validation consistency.

### I2. No tests for adapter-level `_handle_session_status`

**File:** `tests/unit/test_discord_adapter.py`, `tests/unit/test_telegram_adapter.py`, `tests/unit/test_agent_coordinator.py`

Zero tests cover the three adapter handlers added by this change:

- Discord: `_handle_session_status` send/edit/fallback path (including `status_message_id` persistence)
- Telegram: `_handle_session_status` footer update path
- WS broadcast: `api_server._handle_session_status_event`

These are the R3 acceptance criteria paths. The Discord edit-then-fallback-to-send logic is particularly stateful and untested.

### I3. No tests for coordinator status emission or stall detection behavior

**File:** `tests/unit/test_agent_coordinator.py`

No test verifies that:

- `handle_user_prompt_submit` emits `accepted` status
- `handle_tool_use` emits `active_output` and cancels stall task
- `handle_agent_stop` emits `completed` and cancels stall task
- The `_schedule_stall_detection` coroutine transitions `accepted` → `awaiting_output` → `stalled` on timeout
- Cancellation of stall task on output arrival prevents stale transitions

This is the core behavioral contract for R1, R2, and R4.

### I4. Stall watcher task not tracked in `_background_tasks`

**File:** `teleclaude/core/agent_coordinator.py:496-498`

The stall task is stored only in `_stall_tasks`, not in `_background_tasks`. Tasks in `_background_tasks` have a done-callback (`_on_done`) that handles exceptions. If `_emit_status_event` raises an uncaught exception inside the watcher, it will be silently swallowed as an unhandled task exception at GC time.

**Fix:** Add the stall task to `_background_tasks`, or add a broad exception handler within `_stall_watcher`.

---

## Suggestions

### S1. `next()` without default in test assertions

**File:** `tests/unit/test_agent_activity_events.py:218,259,373`

Three test locations use `next(c[0][1] for c in ... if ...)` without a `default` argument. If the filter finds no match, `StopIteration` is raised instead of a descriptive assertion failure. Use `next(..., None)` with an explicit `assert` for clearer test diagnostics.

### S2. Inconsistent assertion style in `test_handle_tool_done`

**File:** `tests/unit/test_agent_activity_events.py:139`

`test_handle_tool_done_emits_activity_event` still uses `assert_called_once()` while all other handler tests now filter by event type. Currently correct (tool_done doesn't emit status), but creates a fragile inconsistency.

---

## Paradigm-Fit Assessment

1. **Data flow:** Status transitions are driven from core (`agent_coordinator.py`) through `status_contract.py` validation, fanned out via `event_bus`. Adapters subscribe and render — no adapter invents semantic status independently. This follows the established event-driven data flow paradigm. **Pass** — except for C1/C2 where the close/error paths bypass the coordinator, creating a parallel emission path in `api_server.py`.

2. **Component reuse:** `_format_lifecycle_status` is defined once in `UiAdapter` base class and inherited by Discord/Telegram. `_handle_session_status` is a no-op in the base and overridden per adapter. This follows the existing adapter inheritance pattern. **Pass.**

3. **Pattern consistency:** The new `SessionStatusContext` dataclass follows the frozen-dataclass event context pattern. The DTO follows the existing Pydantic model pattern. Event subscription follows the `event_bus.subscribe` pattern. Stall detection follows the async task pattern (though not tracked in `_background_tasks`). **Pass** with the I4 caveat.

---

## Requirements Traceability

| Req                                    | Status  | Evidence                                                                     |
| -------------------------------------- | ------- | ---------------------------------------------------------------------------- |
| R1. Core-owned status truth            | Partial | Core computes status, but close/error paths bypass core (C1, C2)             |
| R2. Canonical status contract          | Pass    | `status_contract.py` defines vocabulary, validation, required fields         |
| R3. Capability-aware adapter rendering | Partial | Adapters implemented but untested (I2), Discord deserialization broken (C3)  |
| R4. Truthful inactivity behavior       | Partial | Stall detection implemented but leaks on close/error (C1, C2), untested (I3) |
| R5. Observability and validation       | Partial | Contract tests pass, but no adapter/coordinator integration tests (I2, I3)   |

---

## Summary

The architectural design is sound: a single core-owned contract module validates all status transitions, and adapters render canonical events via the existing event bus pattern. The contract module itself (`status_contract.py`) is clean and well-tested in isolation.

However, three critical gaps prevent approval:

1. Stall tasks leak on session close and agent error, producing spurious status events for dead sessions.
2. Discord `status_message_id` is not round-tripped through `from_json()`, breaking edit-in-place after daemon restart.
3. The close/error terminal paths bypass the coordinator and contract validation.

These are all fixable without architectural changes.
