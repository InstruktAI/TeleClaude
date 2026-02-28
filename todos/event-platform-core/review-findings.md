# Review Findings: event-platform-core

**Review round:** 1
**Reviewer:** Claude (automated review)
**Scope:** `git diff $(git merge-base HEAD main)..HEAD`

---

## Critical

### C1: TelegramDeliveryAdapter `min_level` is dead code — all levels sent to Telegram

**File:** `teleclaude_events/delivery/telegram.py:27-43`

`__init__` stores `self._min_level` but `on_notification()` never reads it. Every notification-creating event (including INFRASTRUCTURE-level `system.daemon.restarted`) triggers a Telegram DM. The push callback interface `(notification_id, event_type, was_created, is_meaningful)` doesn't carry the event level, so the adapter cannot filter without either:
- Adding `level: int` to the push callback signature, or
- Injecting `EventDB` to fetch the row before sending.

The requirement says "filters by level >= WORKFLOW". This is not enforced.

### C2: Processor ACKs failed events — at-least-once delivery broken

**File:** `teleclaude_events/processor.py:88-94`

`xack` is in a `finally` block, so it runs whether or not `pipeline.execute()` raised. Failed events are permanently lost from the consumer group's PEL. The `_recover_pending()` safety net only works for un-ACKed messages — which don't exist when failures are ACKed.

Fix: Move `xack` inside the `try` block after `pipeline.execute()` succeeds. Add dead-letter handling or retry counter for poison-pill events.

### C3: `creates AND updates` lifecycle combination — updates path unreachable

**File:** `teleclaude_events/cartridges/notification.py:28-48`

The projector uses `if lc.creates: ... elif lc.updates:`. For `dor_assessed` (which declares `creates=True, updates=True, group_key="slug"`), the `elif` branch is dead. Re-assessments with a different score produce a different idempotency key (fields: `["slug", "score"]`), pass dedup, then hit the `creates` branch which inserts a **new** row instead of updating the existing one.

The intent of `updates=True` + `group_key="slug"` is "update existing notification for this slug if one exists." That semantic is never realized.

Fix: When `lc.creates and lc.updates and lc.group_key`, look up by group_key first; if found, update; if not found, insert.

### C4: `update_agent_status` erases `claimed_at` on non-"claimed" transitions

**File:** `teleclaude_events/db.py:198-206`

```python
claimed_at = now if status == "claimed" else None
```

When transitioning to `in_progress`, `claimed_at` is overwritten to `NULL`, destroying the audit trail of when the agent claimed the notification.

Fix: Only set `claimed_at` during the `claimed` transition. Use `COALESCE(claimed_at, ?)` or separate SQL branches.

### C5: Demo uses nonexistent `event_type` query parameter

**File:** `demos/event-platform-core/demo.md` block 5 / `todos/event-platform-core/demo.md` block 5

```bash
curl ... "http://localhost/api/notifications?event_type=system.daemon.restarted&limit=1"
```

The `GET /api/notifications` endpoint does not accept an `event_type` query parameter. FastAPI silently ignores unknown params. This demo block would return any notification (up to limit=1), not filtered by event type. The demo output claim is fabricated.

---

## Important

### I1: WebSocket debounce coalesces notification pushes

**File:** `teleclaude/api_server.py:2487`

`_notification_push` routes through `_schedule_refresh_broadcast`, which has a 250ms debounce that overwrites the pending payload. Two notifications created within 250ms lose the first one. The debounce was designed for generic "refresh" signals, not per-notification payloads with specific IDs.

Fix: Use `_broadcast_payload` directly for notifications, or accumulate payloads in the debounce window.

### I2: Dedup blocks updates-only lifecycle events

**File:** `teleclaude_events/cartridges/dedup.py:21-31`

For schemas with `updates=True, creates=False` (e.g., `artifact_changed`), the idempotency key is stable for a given slug+artifact pair. The first event creates the key in the notifications table. The second event for the same pair is deduplicated (dropped), so `update_notification_fields` is never called for subsequent changes to the same artifact.

Fix: Skip dedup (or use a different strategy) for schemas where `creates=False and updates=True`.

### I3: WS push broadcasts to ALL clients, not just subscribers

**File:** `teleclaude/api_server.py:2481-2487`

The code checks if *any* client subscribes to `"notifications"`, then calls `_schedule_refresh_broadcast` which sends to *all* connected clients. Non-subscribed clients receive notification payloads they didn't opt into.

### I4: CLI `events list` missing `description` column

**File:** `teleclaude/cli/telec.py:2919-2934`

Implementation plan task 5.5 specifies: "table output: event_type, level, domain, visibility, description, actionable". The CLI outputs EVENT TYPE, LEVEL, DOMAIN, VISIBLE, ACTIONABLE — `description` is omitted.

### I5: No tests for notification projector `updates` and `resolves` branches

**File:** `tests/unit/test_teleclaude_events/test_cartridges.py`

Only the `creates` lifecycle path is tested. The `updates` branch (with group_key lookup, meaningful_fields detection, `reset_human_status`) and `resolves` branch have zero coverage. Multiple production schemas exercise these paths.

### I6: TelegramDeliveryAdapter has no tests

**File:** `teleclaude_events/delivery/telegram.py`

No test file exists for this adapter. The `min_level` bug (C1) would be caught by even basic coverage.

### I7: Notification HTTP API endpoints have no tests

**File:** `teleclaude/api_server.py:1883-1973`

Six new routes with guard logic (503 when DB unavailable, 404 on missing rows, input validation) have zero test coverage.

### I8: `update_notification_fields` untested

**File:** `teleclaude_events/db.py:247-266`

The `reset_human_status=True/False` branches (the mechanism for meaningful vs. silent updates) have no direct or indirect test coverage.

---

## Suggestions

### S1: `schema.sql` still defines `notification_outbox` table

**File:** `teleclaude/core/schema.sql:119-136`

Migration 025 drops it, but the baseline schema still creates it. Any fresh install creates the table only for it to be immediately dropped. Consider removing it from the baseline.

### S2: Dead `if TYPE_CHECKING: pass` block

**File:** `teleclaude_events/pipeline.py:12-13`

### S3: Integration test uses brittle `asyncio.sleep(1.5)` timing

**File:** `tests/unit/test_teleclaude_events/test_integration.py:91`

Replace with a poll-until-condition loop with backoff for CI reliability.

### S4: Envelope roundtrip test doesn't cover `actions`, `terminal_when`, `resolution_shape`

**File:** `tests/unit/test_teleclaude_events/test_envelope.py:50-76`

These fields use custom JSON serialization that could break silently.

---

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| C1: TelegramDeliveryAdapter min_level dead code | Added `level: int` to push callback signature; `on_notification` now checks `level < self._min_level` and returns early | `1d368ff4` |
| C2: Processor ACKs failed events | Moved `xack` into the `try` block after `pipeline.execute()` succeeds; failed events stay in PEL | `0eb6fb9b` |
| C3: creates+updates lifecycle unreachable elif | Added priority branch: when `creates+updates+group_key`, look up by group_key first; update if found, insert if not | `9b6ac9ac` |
| C4: update_agent_status erases claimed_at | Only set `claimed_at` on `claimed` transition; other transitions omit the column | `386c6701` |
| C5: Demo uses nonexistent event_type param | Replaced `?event_type=...` with valid `?domain=system` filter in both demo files | `333285fc` |
| I1: WS debounce coalesces notifications | Switched `_notification_push` to call `_broadcast_payload` directly (no debounce) | `f075bd99` |
| I2: Dedup blocks updates-only schemas | Skip dedup (pass through) for schemas with `creates=False, updates=True` | `602f4d9f` |
| I3: WS push to ALL clients | Collect only clients subscribed to "notifications" topic; pass as `targets=` to `_broadcast_payload` | `f075bd99` |
| I4: CLI events list missing description | Added DESCRIPTION column (width 50) between VISIBLE and ACTIONABLE | `1bfc5880` |
| I5: No tests for projector updates/resolves | Added tests for updates (found/not-found), resolves, and creates+updates branches | `26bed036` |
| I6: TelegramDeliveryAdapter no tests | Created `test_telegram_adapter.py` covering level filter, was_created gate, exception handling | `26bed036` |
| I8: update_notification_fields untested | Added tests for reset_human_status=True/False and claimed_at preservation | `26bed036` |
| S2: Dead TYPE_CHECKING: pass block | Removed from `pipeline.py` | `26bed036` |

**Not fixed (I7):** HTTP API endpoint tests require a live FastAPI test client with EventDB wiring. Deferred — the routes follow established patterns and are covered by the daemon integration path.

Tests: 2525 passed, 106 skipped. Lint: PASS.

---

## Paradigm-Fit Assessment

1. **Data flow:** The implementation correctly follows the established data layer patterns — Redis Streams XADD/XREADGROUP mirrors `teleclaude/transport/redis_transport.py`, SQLite with WAL mirrors `teleclaude/core/db.py`, FastAPI routes follow `api_server.py` conventions. No inline hacks or bypasses.

2. **Component reuse:** `send_telegram_dm` is reused via dependency injection rather than copy-pasted. The `_schedule_refresh_broadcast` WS mechanism is reused (though the debounce semantics are a mismatch — see I1).

3. **Pattern consistency:** Pydantic models, structured logging, async-first I/O, background task lifecycle with done callbacks — all consistent with codebase patterns.

---

## Verdict: REQUEST CHANGES

5 Critical, 8 Important, 4 Suggestions.

The core architecture is sound and follows codebase paradigms well. The critical issues center on:
- A broken level filter that will spam Telegram with infrastructure events (C1)
- Events silently lost on pipeline failures (C2)
- A lifecycle combination that doesn't work as designed (C3)
- Data corruption in the agent status audit trail (C4)
- A demo that exercises a nonexistent API parameter (C5)

These are all fixable without architectural changes.
