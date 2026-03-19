# Performance Report: asyncio Task Accumulation and Memory Pressure

**Date:** 2026-03-19
**Observed symptom:** `Resource pressure: asyncio_tasks=6790` (threshold: 500)
**Status:** Open — fixes pending

---

## 1. Executive summary

The daemon's asyncio event loop is accumulating tasks far beyond healthy levels (6790 vs
threshold of 500). A healthy daemon should have ~50–100 tasks (infrastructure loops + ~3 per
active session). At 6790, the process is under severe resource pressure — each task consumes
memory, GC time, and event loop scheduling overhead.

Root causes fall into three categories:
1. **Unbounded fire-and-forget task creation** — hot paths that create tasks without
   backpressure or lifecycle management
2. **Untracked tasks** — `asyncio.create_task()` calls that bypass the `TaskRegistry`,
   making them invisible to monitoring and shutdown
3. **Uvicorn/FastAPI degradation** — the HTTP server stack itself accumulates internal state
   over time (3 months of investigation, no root cause found — see
   `todos/api-migration-research.md`)

---

## 2. Findings

### 2.1 CRITICAL — Event pipeline fan-out has no backpressure

**File:** `teleclaude/events/pipeline.py:91`

Every event that passes through the system pipeline creates a `domain_pipeline_fanout` task.
The task is tracked in `_pending_fanout_tasks` (set with discard callback), but there is
**no limit on how many can accumulate**. If domain pipeline processing is slower than event
ingestion, this set grows without bound.

```python
task = asyncio.create_task(
    self._run_domain_pipelines(current),
    name="domain_pipeline_fanout",
)
self._pending_fanout_tasks.add(task)
task.add_done_callback(self._pending_fanout_tasks.discard)
```

This is the **most likely source of the 6790 task count** because:
- Every event generates one task (high frequency)
- All tasks have the same name (`domain_pipeline_fanout`) — indistinguishable in monitoring
- Domain pipelines do DB writes + cartridge processing (slow relative to event rate)
- No cap, no warning, no drop logic

**Fix:** Add backpressure. Options:
- **Semaphore** — `asyncio.Semaphore(max_concurrent)` in `_run_domain_pipelines`. Blocks the
  system pipeline if domain processing is behind. Pros: no event loss. Cons: slows event
  ingestion under load.
- **Bounded set + warn/drop** — if `len(_pending_fanout_tasks) > MAX`, log warning and skip
  domain fan-out for that event. Pros: system pipeline never blocks. Cons: domain events
  (notifications, signals) may be lost under extreme load.
- **Recommended:** Semaphore with a generous bound (e.g., 500). Warn at 80% capacity. This
  preserves all events while providing backpressure feedback.

**Priority:** P0 — this is the primary contributor to the task count.

---

### 2.2 CRITICAL — Monitoring has no task name breakdown

**File:** `teleclaude/services/monitoring_service.py:164-175`

When resource pressure is detected, `_check_pressure` logs the count but not which task names
are accumulating. Without a name breakdown, diagnosing the source requires code analysis
instead of log inspection.

```python
def _check_pressure(self, snapshot):
    tasks = snapshot.get("asyncio_tasks")
    if isinstance(tasks, int) and tasks > _ASYNCIO_TASKS_WARN:
        logger.warning("Resource pressure: asyncio_tasks=%d exceeds threshold %d", tasks, _ASYNCIO_TASKS_WARN)
```

**Fix:** When pressure fires, dump top task names:
```python
if isinstance(tasks, int) and tasks > _ASYNCIO_TASKS_WARN:
    all_tasks = asyncio.all_tasks()
    name_counts: dict[str, int] = {}
    for t in all_tasks:
        name = t.get_name()
        name_counts[name] = name_counts.get(name, 0) + 1
    top_names = sorted(name_counts.items(), key=lambda x: -x[1])[:15]
    logger.warning(
        "Resource pressure: asyncio_tasks=%d exceeds threshold %d | top: %s",
        tasks, _ASYNCIO_TASKS_WARN,
        ", ".join(f"{n}={c}" for n, c in top_names),
    )
```

**Priority:** P0 — deploy this first. It tells us exactly what's accumulating so we fix the
right thing instead of guessing.

---

### 2.3 HIGH — Untracked fire-and-forget tasks (no reference, no cleanup)

These `asyncio.create_task()` calls have no stored reference. The task object exists only in
the event loop's internal set. If the coroutine hangs or is slow, the task accumulates
invisibly. GC cannot collect it because the event loop holds a strong reference.

| File | Line | What it does | Frequency |
|---|---|---|---|
| `core/tmux_io.py` | 103 | DB update (session status) | Every tmux send |
| `core/command_handlers/_agent.py` | 330 | Checkpoint injection after restart | Per agent restart |
| `services/maintenance_service.py` | 169 | Restore tmux session | Per stale session on startup |
| `api/sessions_actions_routes.py` | 438 | Agent restart command | Per restart request |
| `api/ws_mixin.py` | 218 | Initial remote cache refresh | Per WS connect (when no registry) |
| `deployment/handler.py` | 158 | Execute deployment update | Per deployment event |

**Impact ranking by frequency:**
- `tmux_io.py:103` — **highest frequency**. Called every time any message is sent to any tmux
  session. If the DB write is slow (WAL contention, disk I/O), tasks pile up.
- `sessions_actions_routes.py:438` — moderate frequency but the restart operation is slow
  (tmux teardown + recreation), so the task lives a long time.
- The rest are low frequency.

**Fix for each:**
- `tmux_io.py:103` — `await` the DB call instead of fire-and-forget. We're already in an
  async context and the next line also awaits. No reason to fire-and-forget.
- `command_handlers/_agent.py:330` — route through `TaskRegistry.spawn()`.
- `maintenance_service.py:169` — route through `TaskRegistry.spawn()`.
- `sessions_actions_routes.py:438` — route through `TaskRegistry.spawn()`.
- `ws_mixin.py:218` — fallback path when no `task_registry` is available. Add a local
  `_pending_tasks` set like the pipeline does.
- `deployment/handler.py:158` — has a `done_callback` for logging but no stored reference.
  Store in a module-level set and discard on completion.

**Priority:** P1 — each is a small fix but collectively they contribute to task drift.

---

### 2.4 HIGH — DaemonSession background task cap is a symptom, not a fix

**File:** `teleclaude/daemon_session.py:120-130`

```python
def _queue_background_task(self, coro, label):
    if len(self._background_tasks) > 200:
        logger.warning("Background task cap reached (%d), skipping %s", ...)
        return  # SILENTLY DROPS THE TASK
    task = asyncio.create_task(coro)
    self._track_background_task(task, label)
```

The 200-task cap prevents unbounded growth but **silently drops work** when hit. This is a
band-aid that masks the real problem: if 200 background tasks are pending, something upstream
is creating them faster than they complete.

**Fix:** Add logging for _what_ task is being dropped (the `label` is already there, good).
Add a metric for drop count. Then investigate why the cap is being hit — the cap itself is
fine as a safety valve, but dropping work without investigation means silent failures.

**Priority:** P1

---

### 2.5 MEDIUM — Agent coordinator has unbounded background task set

**File:** `teleclaude/core/agent_coordinator/_coordinator.py:82-99`

```python
def _queue_background_task(self, coro, label):
    task = asyncio.create_task(coro)
    self._background_tasks.add(task)
    # ... done callback discards from set
```

Unlike `DaemonSession`, this has **no cap at all**. If background tasks pile up (e.g., slow
DB writes during heavy hook processing), `_background_tasks` grows without limit.

**Fix:** Add the same 200-cap as DaemonSession, with warning logging.

**Priority:** P2

---

### 2.6 MEDIUM — Operations service creates untracked heartbeat + progress tasks

**File:** `teleclaude/core/operations/service.py:311-321, 383-391`

Each running operation creates:
- A `heartbeat_task` (long-lived, runs until operation completes)
- Multiple `_record_progress` tasks (fire-and-forget DB writes)

The progress tasks are tracked in a local `progress_tasks` set (good), but heartbeat tasks
are only stored in a local variable — if the operation runner is cancelled before awaiting
the heartbeat cancel, the task leaks.

**Fix:** Ensure heartbeat tasks are cancelled in all exit paths (including `CancelledError`).
Currently the `finally` block handles this, but verify it's airtight.

**Priority:** P2

---

### 2.7 MEDIUM — Redis transport spawns tasks outside registry when registry unavailable

**File:** `teleclaude/transport/redis_transport/_refresh.py:197-202`

```python
def _spawn_refresh_task(self, coro, *, key):
    if self.task_registry:
        task = self.task_registry.spawn(coro, ...)
    else:
        task = asyncio.create_task(coro)  # No registry — untracked
```

Also: `teleclaude/api/ws_mixin.py:218, 471, 500` — same pattern. Falls back to raw
`create_task` when `task_registry` is None.

**Fix:** Ensure `task_registry` is always injected. If that's not feasible, add a local
`_pending_tasks` set as fallback with discard callbacks.

**Priority:** P2

---

### 2.8 LOW — Polling coordinator tasks tracked with done callback only

**File:** `teleclaude/core/polling_coordinator.py:344`

Per-session poller tasks are created with a done callback but stored only indirectly via the
`_register_polling` / `_deregister_polling` mechanism. If registration state gets out of sync
(e.g., crash during setup), the task reference is lost.

**Fix:** No immediate action needed — the registration mechanism works. Monitor for orphaned
pollers via the task name breakdown (2.2).

**Priority:** P3

---

## 3. Uvicorn/FastAPI degradation (existing research)

See `todos/api-migration-research.md` for the full analysis. Summary:
- The uvicorn ASGI server degrades over time with socket problems
- 3 months of debugging, no root cause found
- Extensive monitoring/restart infrastructure built to cope
- **This will be addressed by the TypeScript migration** — not a short-term fix target

For the short term, the asyncio task fixes above will reduce event loop pressure, which may
indirectly improve uvicorn stability.

---

## 4. Recommended fix order

| # | Fix | File(s) | Priority | Effort | Impact |
|---|-----|---------|----------|--------|--------|
| 1 | Task name breakdown in pressure warning | `monitoring_service.py` | P0 | 15 min | Diagnostic — enables all other fixes |
| 2 | Pipeline fan-out backpressure (semaphore) | `events/pipeline.py` | P0 | 30 min | Likely fixes the 6790 task count |
| 3 | Await DB update in tmux_io | `core/tmux_io.py` | P1 | 5 min | Eliminates highest-frequency untracked task |
| 4 | Route untracked tasks through registry | 5 files (see 2.3) | P1 | 30 min | Closes all fire-and-forget leaks |
| 5 | Cap agent_coordinator background tasks | `agent_coordinator/_coordinator.py` | P2 | 10 min | Safety valve |
| 6 | Ensure heartbeat cleanup in operations | `operations/service.py` | P2 | 15 min | Prevent slow leak under heavy ops |
| 7 | Inject task_registry everywhere | `_refresh.py`, `ws_mixin.py` | P2 | 20 min | Close registry fallback gaps |

**Total estimated effort:** ~2 hours of focused work. All fixes are small, isolated, and
independently deployable. Deploy #1 first, restart daemon, observe next pressure event to
confirm which task names dominate, then deploy #2.

---

## 5. Verification

After each fix:
1. `make restart && make status`
2. Monitor: `instrukt-ai-logs teleclaude --since 30m --grep "Resource pressure"`
3. Confirm task count trends downward over time
4. Target: `asyncio_tasks` stays below 200 under normal load, below 500 under peak
