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

Verdict: **REQUEST CHANGES**

I1 (callback crash) and I2 (missing cleanup wiring) are correctness issues that should be fixed before merge. I3 and I4 are lower-priority but should be addressed in the same pass.
