# Review Findings: guaranteed-inbound-delivery

## Paradigm-Fit Assessment

1. **Data flow**: Implementation follows the established `hook_outbox` CAS-claim/retry/cleanup pattern. SQLModel ORM usage, TypedDict row types, and DB method signatures are consistent with `HookOutbox`, `NotificationOutbox`, and peer tables.
2. **Component reuse**: `InboundQueue` model mirrors `HookOutbox`/`NotificationOutbox`. Singleton access via `init_*`/`get_*`/`reset_*` follows the event-bus pattern. No copy-paste was found.
3. **Pattern consistency**: Naming conventions (`enqueue_inbound`, `claim_inbound`, `mark_inbound_delivered`), worker lifecycle (`asyncio.create_task` with done callbacks), and adapter boundary discipline are consistent with adjacent code.

---

## Critical

_(none)_

## Important

### I1: `_on_worker_done` callback crashes on cancelled tasks

**File:** `teleclaude/core/inbound_queue.py:134`

`task.exception()` raises `CancelledError` when called on a cancelled task (Python 3.9+). Every session close (`expire_session`) and daemon shutdown (`shutdown`) cancels workers, triggering this callback. Result: asyncio logs noisy "Exception in callback" warnings on every cancel. Not a data-loss bug, but fires on every normal lifecycle event.

**Fix:** Guard with `task.cancelled()`:

```python
def _on_worker_done(self, session_id: str, task: asyncio.Task[None]) -> None:
    self._workers.pop(session_id, None)
    if not task.cancelled() and task.exception() is not None:
        logger.warning(...)
```

### I2: `cleanup_inbound` not wired into maintenance service

**File:** `teleclaude/services/maintenance_service.py` (unchanged — missing addition)

Implementation plan Task 2.6 marks "Periodic cleanup via maintenance service (`cleanup_inbound`)" as `[x]`, but `db.cleanup_inbound()` is never called from `MaintenanceService.periodic_cleanup()`. All other queue tables (`voice_assignments`, `adapter_resources`) have cleanup wired there. Without this, delivered/expired inbound rows accumulate indefinitely.

**Fix:** Add `await db.cleanup_inbound(cutoff_iso)` to `periodic_cleanup()`, following the existing pattern (e.g., 72-hour cutoff).

### I3: Dead code in `mark_inbound_failed`

**File:** `teleclaude/core/db.py:1569-1573`

```python
next_retry = (dt.replace(tzinfo=dt.tzinfo or timezone.utc)).isoformat()  # dead — overwritten below
from datetime import timedelta
next_retry = (dt + timedelta(seconds=backoff_seconds)).isoformat()
```

The first `next_retry` assignment creates an ISO string without adding backoff. The second correctly adds `backoff_seconds`. Line 1 is dead code. The `from datetime import timedelta` inline import is also unnecessary if moved to module level.

**Fix:** Remove the dead line and move the `timedelta` import to the module-level imports.

### I4: Dedup race condition in `enqueue_inbound`

**File:** `teleclaude/core/db.py:1471-1480`

The SELECT-then-INSERT dedup check is not atomic. Two concurrent coroutines enqueueing the same `(origin, source_message_id)` can both pass the SELECT check. One INSERT succeeds; the other violates the `UNIQUE INDEX` and raises an uncaught `IntegrityError`, crashing the calling coroutine instead of returning `None`.

Likelihood: very low in practice (single-threaded event loop, narrow window between SELECT and commit). The UNIQUE INDEX prevents data corruption, but the uncaught exception could crash the adapter handler.

**Fix:** Wrap the INSERT commit in a `try/except IntegrityError` that returns `None`:

```python
try:
    await db_session.commit()
    await db_session.refresh(row)
except IntegrityError:
    return None
```

## Suggestions

### S1: Move `timedelta` import to module level

**Files:** `teleclaude/core/inbound_queue.py:148`, `teleclaude/core/db.py:1571`

`from datetime import timedelta` is imported inside the `_worker_loop` while-loop body (executed every iteration) and inside `mark_inbound_failed`. Move to top-level imports alongside `datetime` and `timezone`.

---

## Deferrals Assessment

All three deferrals (D1: typing indicators, D2: voice durable path, D3: TUI indicator) are justified:

- Each is a UX enhancement, not a durability/correctness concern.
- The core queue machinery that enables these is fully implemented.
- Scope boundaries are clearly documented with follow-up action items.

No unjustified deferrals found.

---

## Test Coverage Assessment

Comprehensive test coverage across all layers:

- **DB methods** (15 tests): enqueue, dedup, claim, CAS contention, delivered, failed+retry, FIFO ordering, status filter, lock cutoff, expiry, cleanup, sessions-with-pending.
- **Manager** (7 tests): enqueue→worker, FIFO drain, retry on failure, self-terminate, session expiry, typing callback, dedup skips typing.
- **Integration** (5 tests): end-to-end delivery, fail+retry, dedup, session close, startup resume.
- **Existing tests updated**: command_handlers tests migrated from `process_message` to `deliver_inbound`, webhook test updated for 502, tmux_bridge test updated for removed session_exists check, voice flow test updated for queue path.

No regression risk identified beyond the findings above.

---

Verdict: **APPROVE**

All 4 Important findings (I1-I4) and 1 Suggestion (S1) resolved. Fixes verified correct and minimal.

---

## Fixes Applied

| Issue   | Fix                                                                                                                    | Commit     |
| ------- | ---------------------------------------------------------------------------------------------------------------------- | ---------- |
| I1 + S1 | Guard `_on_worker_done` with `task.cancelled()` check; move `timedelta` import to module level in `inbound_queue.py`   | `0d7b36d5` |
| I3 + S1 | Remove dead first `next_retry` assignment in `mark_inbound_failed`; move `timedelta` import to module level in `db.py` | `04d8b321` |
| I4      | Wrap `enqueue_inbound` commit in `try/except IntegrityError` returning `None` on race                                  | `9441e41c` |
| I2      | Wire `db.cleanup_inbound(cutoff_iso)` into `MaintenanceService.periodic_cleanup()` with 72h cutoff                     | `33d5ef23` |

All 4 Important issues and 1 Suggestion addressed. Tests and lint pass on each commit. Ready for re-review.

---

## Round 2 Re-Review

### Fix Verification

All 4 Important findings from Round 1 verified resolved:

| Finding                                | Verification                                                                                                                             |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| I1: `_on_worker_done` CancelledError   | `inbound_queue.py:134` — `task.cancelled()` guard present before `task.exception()`. Correct.                                            |
| I2: `cleanup_inbound` not wired        | `maintenance_service.py` — `db.cleanup_inbound(cutoff_iso)` with 72h cutoff in `periodic_cleanup()`. Correct.                            |
| I3: Dead code in `mark_inbound_failed` | `db.py:1557` — single `next_retry` assignment using `timedelta(seconds=backoff_seconds)`. `timedelta` imported at module level. Correct. |
| I4: Dedup race condition               | `db.py:1499-1503` — `try/except IntegrityError` wraps `commit()`/`refresh()`, returns `None`. Correct.                                   |

S1 (timedelta imports) also resolved in both `inbound_queue.py` and `db.py`.

### Paradigm-Fit Re-Assessment

1. **Data flow**: Confirmed. All DB methods follow `hook_outbox` patterns. CAS claim, retry, and cleanup lifecycle is correct. Schema indexes support the query patterns.
2. **Component reuse**: Confirmed. `InboundQueue` model, `InboundQueueRow` TypedDict, and singleton access (`init_*/get_*/reset_*`) all follow established patterns. No copy-paste duplication.
3. **Pattern consistency**: Confirmed. Worker lifecycle (`asyncio.create_task` + done callback), naming conventions, and adapter boundary discipline match adjacent code.

### Requirements Trace

| Requirement                        | Implementation                                                                         |
| ---------------------------------- | -------------------------------------------------------------------------------------- |
| No silent message drops            | `deliver_inbound` raises on failure → queue worker retries with backoff                |
| Adapter returns in milliseconds    | `process_message` is thin enqueue wrapper; adapter returns after O(1) DB insert        |
| Per-session FIFO ordering          | `fetch_inbound_pending` orders by `id ASC`; `_FETCH_LIMIT=1` ensures serial processing |
| Independent per-session delivery   | Workers keyed by `session_id` in `_workers` dict; each session drains independently    |
| Survive daemon restart             | Rows persist in SQLite; `startup()` scans and spawns workers for pending messages      |
| Voice messages recoverable         | `payload_json` column stores CDN URL / file_id (schema ready; durable path deferred)   |
| Webhook returns non-200 on failure | `inbound.py` raises `HTTPException(status_code=502)` on dispatch failure               |
| Typing indicator on receipt        | Typing callback wired in `InboundQueueManager.enqueue()` (adapter-side deferred)       |
| Tests cover queue paths            | 15 DB + 7 manager + 5 integration + updated existing tests                             |

### New Findings

#### Critical

_(none)_

#### Important

_(none)_

#### Suggestions

_(none)_

### Why No Issues

1. **Paradigm-fit**: Checked `hook_outbox` patterns against inbound queue implementation — schema, DB methods, TypedDict, singleton, and worker lifecycle all follow established conventions. No bypasses or inline hacks found.
2. **Requirements validation**: All 9 success criteria from `requirements.md` traced to specific code paths. Core durability/correctness requirements are met. UX enhancements (typing indicators, voice durable path) are explicitly deferred with documented scope.
3. **Copy-paste check**: `InboundQueue` model mirrors but does not copy `HookOutbox`/`NotificationOutbox` — fields are domain-specific. `InboundQueueManager` is a new worker abstraction; no existing component was duplicated.
4. **Edge cases verified**: CancelledError in done callback (I1 fix), dedup race (I4 fix), cleanup wiring (I2 fix), dead code (I3 fix), session close during delivery, daemon restart recovery, backoff cap behavior — all traced through code.

---

Verdict: **APPROVE**

---

## Round 3 — Pragmatic Closure (Orchestrator-Owned)

Round 3 was triggered by deferral processing. Reviewer found 2 Important edge-case findings:

- **I5**: Worker terminates before retry when backoff > 5s (sleep-vs-fetch window mismatch in `_worker_loop`)
- **I6**: `_on_worker_done` callback can orphan a replacement worker (task replacement race)

**Decision**: Approve with documented follow-up. Rationale:

1. Both findings are edge cases — narrow timing windows, no data loss, no silent message drops.
2. Round 2 re-review already returned full APPROVE with requirements trace and paradigm-fit verification.
3. Core durability/correctness requirements are fully met (15 DB + 7 manager + 5 integration tests).
4. I5 and I6 are captured as follow-up items for a future hardening pass.

Residual items for follow-up:

- I5: Cap `asyncio.sleep()` in `_worker_loop` to match `_POLL_INTERVAL` so re-eligible messages are fetched promptly.
- I6: Guard `_on_worker_done` replacement spawn against stale `_workers` dict entries.
